"""会话模块对话框（view 层）。"""
import os
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton,
    QDialogButtonBox, QComboBox, QFileDialog, QTreeWidget, QTreeWidgetItem,
    QAbstractItemView, QHeaderView, QDialog,
)

from ccui.app.theme import fmt_size, fmt_time
from ccui.app.dialogs import FadeDialog, mk_buttons
from ccui.app.icons import provider_icon, ui_icon
from ccui.app.splash import warning_pixmap
from ccui.provider.data.store import provider_models


class ModelComboBox(QComboBox):
    """Provider→模型级联下拉。外部调 populate(provider_cfg, preselect) 重建条目。

    条目 userData 存模型名；默认模型加「 · 默认」标记；快速模型是 provider 级
    后台设置，不出现在建会话选择中（建会话只决定这次跑哪个模型）。
    池为空时显示占位项（userData=''，model() 返回 '' → 走 provider 默认模型）。
    """

    def populate(self, cfg, preselect=''):
        self.clear()
        models = provider_models(cfg) if cfg else []
        main = (cfg or {}).get('model')
        if not models:
            self.addItem('（该 Provider 暂无模型，用其默认配置启动）', '')
            return
        for m in models:
            self.addItem(m + ('  ·  默认' if m == main else ''), m)
        if preselect:
            idx = self.findData(preselect)
            if idx >= 0:
                self.setCurrentIndex(idx)


def _make_provider_model_rows(label_prov='Provider:'):
    """返回 (prov_row_layout, model_row_layout, cb_provider, cb_model)。

    provider 下拉带图标；模型下拉随 provider 联动。调用方负责 populate + 连接。
    """
    prov_row = QHBoxLayout()
    prov_row.addWidget(QLabel(label_prov))
    cb_provider = QComboBox()
    prov_row.addWidget(cb_provider, 1)
    model_row = QHBoxLayout()
    model_row.addWidget(QLabel('模型:'))
    cb_model = ModelComboBox()
    model_row.addWidget(cb_model, 1)
    return prov_row, model_row, cb_provider, cb_model


class ResumeDialog(FadeDialog):
    """恢复会话：选择权限模式 + Provider（默认 = 该会话上次的）+ 模型。"""

    def __init__(self, default_mode, title_hint, providers, default_provider,
                 parent=None, providers_map=None, default_model=''):
        super().__init__(parent)
        self._pmap = providers_map or {}
        self.setWindowTitle('恢复会话')
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        hint = QLabel(f'会话「{title_hint}」上次使用的权限模式：'
                      f'{"危险模式" if default_mode == "danger" else "正常模式"}')
        hint.setWordWrap(True)
        lay.addWidget(hint)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel('权限模式：'))
        self.cb_mode = QComboBox()
        self.cb_mode.addItem(ui_icon('shield-check', 14), '正常模式', 'normal')
        self.cb_mode.addItem(ui_icon('shield-off', 14, '#ff6961'), '危险模式（跳过权限确认）', 'danger')
        self.cb_mode.setCurrentIndex(1 if default_mode == 'danger' else 0)
        mode_row.addWidget(self.cb_mode, 1)
        lay.addLayout(mode_row)
        prov_row, model_row, self.cb_provider, self.cb_model = _make_provider_model_rows()
        for p in (providers if providers else ['(无)']):
            self.cb_provider.addItem(provider_icon(p), p)
        if default_provider and default_provider in providers:
            self.cb_provider.setCurrentIndex(providers.index(default_provider))
        lay.addLayout(prov_row)
        lay.addLayout(model_row)
        self._populate_model(default_model)
        self.cb_provider.currentTextChanged.connect(lambda *_: self._populate_model())
        lay.addWidget(mk_buttons(self, '恢复'))

    def _populate_model(self, preselect=''):
        prov = self.cb_provider.currentText()
        self.cb_model.populate(self._pmap.get(prov), preselect)

    def mode(self):
        return self.cb_mode.currentData()

    def provider(self):
        return self.cb_provider.currentText()

    def model(self):
        return self.cb_model.currentData() or ''


class NewSessionDialog(FadeDialog):
    """新建会话：工作目录（原生选择器）+ Provider + 模型 + 可选继承会话。"""

    def __init__(self, providers, default_provider, last_cwd, parent=None, sessions=None,
                 providers_map=None):
        super().__init__(parent)
        self._pmap = providers_map or {}
        self.setWindowTitle('新建会话')
        self.setMinimumWidth(440)
        self._sessions = sessions or []
        self._inherit_ids = []
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.dir_edit = QLineEdit(last_cwd or os.path.expanduser('~'))
        self.btn_browse = QPushButton('浏览…')
        self.btn_browse.clicked.connect(self._browse)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(self.btn_browse)
        form.addRow('工作目录', dir_row)
        self.cb_provider = QComboBox()
        for p in (providers if providers else ['(无)']):
            self.cb_provider.addItem(provider_icon(p), p)
        if default_provider and default_provider in providers:
            self.cb_provider.setCurrentIndex(providers.index(default_provider))
        form.addRow('Provider', self.cb_provider)
        self.cb_model = ModelComboBox()
        form.addRow('模型', self.cb_model)
        self._populate_model()
        self.cb_provider.currentTextChanged.connect(lambda *_: self._populate_model())
        self.cb_mode = QComboBox()
        self.cb_mode.addItem(ui_icon('shield-check', 14), '正常模式', 'normal')
        self.cb_mode.addItem(ui_icon('shield-off', 14, '#ff6961'), '危险模式（跳过权限确认）', 'danger')
        form.addRow('权限模式', self.cb_mode)
        inherit_row = QHBoxLayout()
        self.lbl_inherit = QLabel('未选择')
        inherit_row.addWidget(self.lbl_inherit, 1)
        self.btn_inherit = QPushButton('选择继承会话…')
        self.btn_inherit.clicked.connect(self._pick_inherit)
        inherit_row.addWidget(self.btn_inherit)
        form.addRow('继承会话', inherit_row)
        lay.addLayout(form)
        btns = mk_buttons(self, '创建并启动')
        self.btn_ok = btns.button(QDialogButtonBox.StandardButton.Ok)
        # 目录为空时禁用创建（inline 校验：按钮态即反馈）
        self.dir_edit.textChanged.connect(self._sync_ok)
        self._sync_ok()
        lay.addWidget(btns)

    def _sync_ok(self):
        self.btn_ok.setEnabled(bool(self.dir_edit.text().strip()))

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, '选择工作目录',
                                             self.dir_edit.text() or os.path.expanduser('~'))
        if d:
            self.dir_edit.setText(d)

    def _pick_inherit(self):
        dlg = InheritDialog(self._sessions, self, title='选择要继承的会话',
                            ok_text='确定', hint='可多选，勾选 0 个则不继承')
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._inherit_ids = dlg.selected_ids()
            self.lbl_inherit.setText(f'已选 {len(self._inherit_ids)} 个' if self._inherit_ids else '未选择')

    def directory(self):
        return self.dir_edit.text().strip()

    def _populate_model(self, preselect=''):
        self.cb_model.populate(self._pmap.get(self.cb_provider.currentText()), preselect)

    def provider(self):
        return self.cb_provider.currentText()

    def model(self):
        return self.cb_model.currentData() or ''

    def mode(self):
        return self.cb_mode.currentData()

    def inherit_ids(self):
        return list(self._inherit_ids)


class InheritDialog(FadeDialog):
    """选择要继承的会话（可多选；勾选 0 个 = 不继承）。

    角色「创建角色会话」与会话模块「新建会话」复用；通过 title/ok_text/hint 调整文案。
    """

    def __init__(self, sessions, parent=None, title='选择要继承的会话',
                 ok_text='开始继承会话', hint='', cwd_visible=False, cwd='',
                 providers=None, default_provider='', providers_map=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 380)
        self._pmap = providers_map or {}
        self._changed_at = 0  # 勾选框默认切换守卫：避免 itemClicked 双重切换
        lay = QVBoxLayout(self)
        if hint:
            h = QLabel(hint)
            h.setWordWrap(True)
            lay.addWidget(h)
        if cwd_visible:
            # 创建角色会话时可选工作目录 + 权限模式
            cwd_row = QHBoxLayout()
            cwd_row.addWidget(QLabel('工作目录：'))
            self.cwd_edit = QLineEdit(cwd or os.path.expanduser('~'))
            self.btn_cwd_browse = QPushButton('浏览…')
            self.btn_cwd_browse.clicked.connect(self._browse_cwd)
            cwd_row.addWidget(self.cwd_edit, 1)
            cwd_row.addWidget(self.btn_cwd_browse)
            lay.addLayout(cwd_row)
            mode_row = QHBoxLayout()
            mode_row.addWidget(QLabel('权限模式：'))
            self.cb_mode = QComboBox()
            self.cb_mode.addItem(ui_icon('shield-check', 14), '正常模式', 'normal')
            self.cb_mode.addItem(ui_icon('shield-off', 14, '#ff6961'), '危险模式（跳过权限确认）', 'danger')
            mode_row.addWidget(self.cb_mode, 1)
            lay.addLayout(mode_row)
            prov_row = QHBoxLayout()
            prov_row.addWidget(QLabel('Provider:'))
            self.cb_provider = QComboBox()
            for p in (providers if providers else ['(无)']):
                self.cb_provider.addItem(provider_icon(p), p)
            if default_provider and default_provider in (providers or []):
                self.cb_provider.setCurrentIndex(providers.index(default_provider))
            prov_row.addWidget(self.cb_provider, 1)
            lay.addLayout(prov_row)
            model_row = QHBoxLayout()
            model_row.addWidget(QLabel('模型:'))
            self.cb_model = ModelComboBox()
            model_row.addWidget(self.cb_model, 1)
            lay.addLayout(model_row)
            self._populate_model()
            self.cb_provider.currentTextChanged.connect(lambda *_: self._populate_model())
        self.list = QTreeWidget()
        self.list.setHeaderLabels(['会话', '时间'])
        self.list.setRootIsDecorated(False)
        # 列分布：标题列 stretch 吃满剩余，时间列收缩到内容
        _h = self.list.header()
        _h.setStretchLastSection(False)
        _h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        _h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        # 纯勾选：点击不整行蓝选，只切换勾选框（与会话列表风格统一）
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.itemClicked.connect(self._toggle_item)  # 点行任意位置即切换勾选
        self.list.itemChanged.connect(lambda *_: setattr(self, '_changed_at', time.time()))
        for s in sessions:
            if s.isLive:
                continue
            item = QTreeWidgetItem([s.title or '(空会话)', fmt_time(s.lastTime)])
            item.setData(0, Qt.ItemDataRole.UserRole, s.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            self.list.addTopLevelItem(item)
        lay.addWidget(self.list)
        btns = mk_buttons(self, ok_text)
        self.btn_ok = btns.button(QDialogButtonBox.StandardButton.Ok)
        if cwd_visible:
            # 目录为空时禁用创建（inline 校验）
            self.cwd_edit.textChanged.connect(self._sync_ok)
            self._sync_ok()
        lay.addWidget(btns)

    def _sync_ok(self):
        if hasattr(self, 'btn_ok') and hasattr(self, 'cwd_edit'):
            self.btn_ok.setEnabled(bool(self.cwd_edit.text().strip()))

    def _toggle_item(self, item, column):
        # 勾选框点击时 Qt 已默认切换，itemChanged 刚更新 _changed_at → 跳过，避免双重切换
        if time.time() - self._changed_at < 0.1:
            return
        item.setCheckState(0, Qt.CheckState.Unchecked if item.checkState(0) == Qt.CheckState.Checked
                           else Qt.CheckState.Checked)

    def _browse_cwd(self):
        d = QFileDialog.getExistingDirectory(self, '选择工作目录', self.cwd_edit.text())
        if d:
            self.cwd_edit.setText(d)

    def directory(self):
        """所选工作目录（未显示 cwd 选择时返回空串）。"""
        edit = getattr(self, 'cwd_edit', None)
        return edit.text().strip() if edit else ''

    def mode(self):
        """所选权限模式（未显示模式选择时默认 normal）。"""
        cb = getattr(self, 'cb_mode', None)
        return cb.currentData() if cb else 'normal'

    def _populate_model(self, preselect=''):
        cb = getattr(self, 'cb_model', None)
        if cb is not None:
            cb.populate(self._pmap.get(self.cb_provider.currentText()), preselect)

    def provider(self):
        """所选 Provider（未显示 Provider 选择时返回 ''）。"""
        cb = getattr(self, 'cb_provider', None)
        return cb.currentText() if cb else ''

    def model(self):
        """所选模型（未显示模型选择时返回 ''）。"""
        cb = getattr(self, 'cb_model', None)
        return (cb.currentData() or '') if cb is not None else ''

    def selected_ids(self):
        return [self.list.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                for i in range(self.list.topLevelItemCount())
                if self.list.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]


class DeleteDialog(FadeDialog):
    """删除确认：列出会话 + 释放大小（清理空会话复用，可自定义文案）。"""

    def __init__(self, items, total_size, parent=None, title='确认删除',
                 confirm_text='确认删除', intro=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(480, 320)
        lay = QVBoxLayout(self)
        if intro is None:
            intro = f'确认删除 {len(items)} 个会话？将释放约 {fmt_size(total_size)}：'
        lay.addWidget(QLabel(intro))
        lst = QTreeWidget(self)
        lst.setHeaderLabels(['会话', '项目'])
        lst.setRootIsDecorated(False)
        _h = lst.header()
        _h.setStretchLastSection(False)
        _h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        _h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for t, proj in items:
            lst.addTopLevelItem(QTreeWidgetItem([t, proj]))
        lay.addWidget(lst)
        warn_row = QHBoxLayout()
        warn_icon = QLabel()
        warn_icon.setPixmap(warning_pixmap(14).scaled(
            14, 14, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        warn_row.addWidget(warn_icon)
        warn_text = QLabel('运行中的会话不会被删除（已自动排除）')
        warn_text.setStyleSheet('color:#f14c4c;')
        warn_row.addWidget(warn_text)
        warn_row.addStretch(1)
        lay.addLayout(warn_row)
        lay.addWidget(mk_buttons(self, confirm_text, danger_ok=True))
