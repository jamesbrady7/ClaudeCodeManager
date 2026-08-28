"""Provider 面板（「模型」tab）：左 provider 列表 + 右详情（baseUrl/key/模型池）。

数据源：ccui.provider.service（cc-config.json 唯一写通道）。写操作经 service 广播
providers.changed → 本面板防抖刷新。启动链的 provider+模型级联在 session/role 对话框。
"""
import os

from PySide6.QtCore import Qt, QSize, QTimer, QFileSystemWatcher, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QLabel, QPushButton, QAbstractItemView,
    QApplication, QMessageBox, QFrame,
)

from ccui.infra.config import CONFIG_DIR, CC_CONFIG_FILE, READONLY
from ccui.infra.signalhub import SignalHub
from ccui.app.theme import COLOR_MUTED
from ccui.app.icons import ui_icon, provider_icon
from ccui.app.widgets import (
    PressButton, FadeMenu, EmptyHint, AccentBarDelegate, ElidedLabel,
)
from ccui.provider.service.provider_service import ProviderService
from ccui.provider.view.dialogs import (
    ProviderEditDialog, AddModelDialog, RenameModelDialog,
)


class ProviderPanel(QWidget):
    status_message = Signal(str, int)
    new_session_requested = Signal(str, str)  # (provider, model)：交主窗转发到会话面板

    def __init__(self, parent=None):
        super().__init__(parent)
        self.service = ProviderService()
        self._providers = {}          # {name: cfg}
        self._default = ''
        self._current = ''
        self._key_revealed = False
        self._reveal_for = ''   # 明文显示状态归属的 provider（reload 不清、换人才清）
        self._build_ui()
        self._setup_watcher()
        self._reload()

    # ---- UI ----
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        bar = QFrame()
        bar.setObjectName('toolbarBar')
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(0, 0, 0, 10)
        self.btn_new = PressButton(' 新建 Provider')
        self.btn_new.setObjectName('btnNew')
        self.btn_new.setIcon(ui_icon('plus', 14, '#ffffff'))
        self.btn_new.clicked.connect(self._new_provider)
        tb.addWidget(self.btn_new)
        self.btn_refresh = QPushButton('刷新')
        self.btn_refresh.clicked.connect(self._reload)
        tb.addWidget(self.btn_refresh)
        self.btn_open = QPushButton(' 打开配置文件')
        self.btn_open.setIcon(ui_icon('folder-open', 14))
        self.btn_open.setToolTip('用系统关联程序打开 cc-config.json')
        self.btn_open.clicked.connect(self._open_config)
        tb.addWidget(self.btn_open)
        tb.addStretch(1)
        self.lbl_stats = QLabel('')
        tb.addWidget(self.lbl_stats)
        root.addWidget(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左：provider 列表
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 4, 0)
        self.provider_list = QListWidget()
        self.provider_list.setObjectName('providerList')
        self.provider_list.setMinimumWidth(200)
        self.provider_list.setIconSize(QSize(26, 26))
        self.provider_list.setItemDelegate(AccentBarDelegate(self.provider_list))
        self.provider_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.provider_list.currentItemChanged.connect(self._on_selected)
        self.provider_list.itemDoubleClicked.connect(self._on_row_double)
        self.provider_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.provider_list.customContextMenuRequested.connect(self._show_provider_menu)
        self._empty_hint = EmptyHint('还没有 Provider，点「新建 Provider」开始', self.provider_list)
        left_lay.addWidget(self.provider_list)
        splitter.addWidget(left)

        # 右：详情
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 0, 0, 0)

        hero = QHBoxLayout()
        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(48, 48)
        hero.addWidget(self.lbl_icon)
        hero.addSpacing(8)
        hcol = QVBoxLayout()
        self.lbl_name = QLabel('选择左侧 Provider')
        self.lbl_name.setStyleSheet('font-size:20px; font-weight:600; color:#f5f5f7;')
        hcol.addWidget(self.lbl_name)
        self.lbl_url = ElidedLabel('')
        self.lbl_url.setStyleSheet(f'color:{COLOR_MUTED};')
        hcol.addWidget(self.lbl_url)
        hero.addLayout(hcol, 1)
        self.btn_set_default = QPushButton('设为默认')
        self.btn_set_default.clicked.connect(self._set_default)
        hero.addWidget(self.btn_set_default)
        rl.addLayout(hero)

        # key 行：掩码 + 显示/隐藏 + 复制
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel('API Key：'))
        self.lbl_key = ElidedLabel('')
        self.lbl_key.setStyleSheet(f'color:{COLOR_MUTED};')
        key_row.addWidget(self.lbl_key, 1)
        self.btn_eye = QPushButton()
        self.btn_eye.setObjectName('iconBtn')
        self.btn_eye.setIcon(ui_icon('eye', 15))
        self.btn_eye.setIconSize(QSize(15, 15))
        self.btn_eye.setFixedSize(30, 28)
        self.btn_eye.setToolTip('显示密钥')
        self.btn_eye.clicked.connect(self._toggle_key)
        key_row.addWidget(self.btn_eye)
        self.btn_copy_key = QPushButton()
        self.btn_copy_key.setObjectName('iconBtn')
        self.btn_copy_key.setIcon(ui_icon('copy', 15))
        self.btn_copy_key.setIconSize(QSize(15, 15))
        self.btn_copy_key.setFixedSize(30, 28)
        self.btn_copy_key.setToolTip('复制密钥')
        self.btn_copy_key.clicked.connect(self._copy_key)
        key_row.addWidget(self.btn_copy_key)
        rl.addLayout(key_row)

        # 操作按钮
        act = QHBoxLayout()
        self.btn_edit = QPushButton(' 编辑信息')
        self.btn_edit.setIcon(ui_icon('settings', 14))
        self.btn_edit.clicked.connect(self._edit_provider)
        self.btn_del = QPushButton(' 删除')
        self.btn_del.setProperty('danger', True)
        self.btn_del.setIcon(ui_icon('trash-2', 14, '#ff6961'))
        self.btn_del.clicked.connect(self._delete_provider)
        self.btn_new_session = QPushButton(' 用此 Provider 新建会话')
        self.btn_new_session.setObjectName('btnSuccess')  # 绿色行动按钮
        self.btn_new_session.setIcon(ui_icon('play', 14, '#ffffff'))
        self.btn_new_session.clicked.connect(self._new_session_here)
        act.addWidget(self.btn_edit)
        act.addWidget(self.btn_del)
        act.addWidget(self.btn_new_session)
        act.addStretch(1)
        rl.addLayout(act)

        # 模型池
        mdl_head = QHBoxLayout()
        t = QLabel('模型池')
        t.setStyleSheet('font-weight:600; color:#f5f5f7;')
        mdl_head.addWidget(t)
        self.lbl_default_hint = QLabel('')
        self.lbl_default_hint.setStyleSheet(f'color:{COLOR_MUTED}; font-size:12px;')
        mdl_head.addWidget(self.lbl_default_hint)
        mdl_head.addStretch(1)
        self.btn_add_model = PressButton(' 添加模型')
        self.btn_add_model.setObjectName('btnNew')  # 与「新建 Provider」同款蓝色主按钮
        self.btn_add_model.setIcon(ui_icon('plus', 14, '#ffffff'))
        self.btn_add_model.clicked.connect(self._add_model)
        mdl_head.addWidget(self.btn_add_model)
        rl.addLayout(mdl_head)

        self.model_tree = QTreeWidget()
        self.model_tree.setColumnCount(4)
        self.model_tree.setHeaderLabels(['模型名', '默认', '快速', ''])
        self.model_tree.setRootIsDecorated(False)
        self.model_tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.model_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.model_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.model_tree.customContextMenuRequested.connect(self._show_model_menu)
        self.model_tree.itemDoubleClicked.connect(self._rename_model_item)
        h = self.model_tree.header()
        # 布局：模型名(定宽,可拖) | 默认(定宽✓) | 快速(定宽✓) | 空列吸收剩余
        # 模型名列**不能**用 ResizeToContents——否则切 provider 时列宽随名字长度变，✓ 列左右跳动
        h.setStretchLastSection(True)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.model_tree.setColumnWidth(0, 240)
        self.model_tree.setColumnWidth(1, 56)
        self.model_tree.setColumnWidth(2, 56)
        for c in (1, 2):
            self.model_tree.headerItem().setTextAlignment(c, Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.model_tree, 1)
        self._model_hint = EmptyHint('还没有模型', self.model_tree)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, 1)

        if READONLY:
            for b in (self.btn_new, self.btn_add_model, self.btn_edit, self.btn_del,
                      self.btn_set_default, self.btn_new_session):
                b.setEnabled(False)

    def _setup_watcher(self):
        self.watcher = QFileSystemWatcher(self)
        for p in (CONFIG_DIR,):
            if os.path.exists(p):
                self.watcher.addPath(p)
        self.watcher.directoryChanged.connect(self._schedule_reload)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(300)
        self.debounce.timeout.connect(self._reload)
        SignalHub.instance().subscribe('providers.changed', self._schedule_reload)

    def _schedule_reload(self, *_):
        self.debounce.start()

    # ---- 数据刷新 ----
    def _reload(self):
        self._default, self._providers = self.service.list_all()
        names = list(self._providers.keys())
        # 记住当前选择（除非被删）
        cur = self._current if self._current in names else (names[0] if names else '')
        self.provider_list.blockSignals(True)
        self.provider_list.clear()
        for n in names:
            it = QListWidgetItem(self._make_icon(n), self._row_label(n))
            it.setData(Qt.ItemDataRole.UserRole, n)
            it.setToolTip(self._row_label(n))
            self.provider_list.addItem(it)
            if n == self._default:
                f = it.font(); f.setBold(True); it.setFont(f)
        self.provider_list.blockSignals(False)
        self._empty_hint.set_empty(len(names) == 0)
        total_models = sum(len(self.service.models_of(self._providers[n])) for n in names)
        self.lbl_stats.setText(
            f'{len(names)} 个 Provider · {total_models} 个模型')
        self.lbl_stats.setStyleSheet(f'color:{COLOR_MUTED};')
        if cur:
            self._select_by_name(cur)
        else:
            self._show_detail('')

    def _make_icon(self, name):
        return provider_icon(name, 26)

    def _row_label(self, name):
        n_models = len(self.service.models_of(self._providers.get(name, {})))
        tag = '  ·  默认' if name == self._default else ''
        return f'{name}{tag}   （{n_models} 模型）'

    def _select_by_name(self, name):
        for i in range(self.provider_list.count()):
            if self.provider_list.item(i).data(Qt.ItemDataRole.UserRole) == name:
                self.provider_list.setCurrentRow(i)
                return
        self.provider_list.setCurrentRow(-1)

    def _on_selected(self, cur, _prev):
        name = cur.data(Qt.ItemDataRole.UserRole) if cur else ''
        self._show_detail(name)

    def _on_row_double(self, item):
        """双击 provider 行 = 用该 provider 新建会话（预置其默认模型）。"""
        if not item or READONLY:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        self._current = name
        self._new_session_here()

    def _show_detail(self, name):
        self._current = name
        if name != self._reveal_for:     # 切换到另一个 provider 才收起明文
            self._key_revealed = False
            self._reveal_for = name
        cfg = self._providers.get(name)
        if not cfg:
            self.lbl_icon.clear()
            self.lbl_name.setText('选择左侧 Provider')
            self.lbl_url.setText('')
            self.lbl_key.setText('')
            self.model_tree.clear()
            self._model_hint.set_empty(True)
            for b in (self.btn_edit, self.btn_del, self.btn_set_default, self.btn_new_session):
                b.setEnabled(False)
            return
        has = not READONLY
        self.btn_edit.setEnabled(has)
        self.btn_del.setEnabled(has)
        self.btn_new_session.setEnabled(has)
        self.btn_set_default.setEnabled(has and name != self._default)
        self.lbl_name.setText(name + ('   ★ 默认' if name == self._default else ''))
        self.lbl_url.setText(cfg.get('baseUrl', ''))
        self.lbl_url.setToolTip(cfg.get('baseUrl', ''))
        self._render_key(cfg)
        # 图标
        self.lbl_icon.setPixmap(self._hero_pixmap(name))
        self._render_models(cfg)

    def _hero_pixmap(self, name):
        return provider_icon(name, 48).pixmap(QSize(48, 48))

    def _render_key(self, cfg):
        key = cfg.get('apiKey', '') or ''
        if self._key_revealed:
            self.lbl_key.setText(key)
            self.btn_eye.setIcon(ui_icon('eye-off', 15))
            self.btn_eye.setToolTip('隐藏密钥')
        else:
            self.lbl_key.setText(self.service.mask_key(key) if key else '（未设置）')
            self.btn_eye.setIcon(ui_icon('eye', 15))
            self.btn_eye.setToolTip('显示密钥')

    def _render_models(self, cfg):
        models = self.service.models_of(cfg)
        main, fast = cfg.get('model'), cfg.get('fastModel')
        center = int(Qt.AlignmentFlag.AlignCenter)
        self.model_tree.clear()
        for m in models:
            item = QTreeWidgetItem([m, '', ''])
            item.setData(0, Qt.ItemDataRole.UserRole, m)
            if m == main:
                item.setText(1, '✓')
                item.setTextAlignment(1, center)
                item.setForeground(1, self._color('#ffd60a'))
                f = item.font(0); f.setBold(True); item.setFont(0, f)
            if m == fast:
                item.setText(2, '✓')
                item.setTextAlignment(2, center)
                item.setForeground(2, self._color('#30d158'))
            self.model_tree.addTopLevelItem(item)
        self._model_hint.set_empty(not models)
        self.lbl_default_hint.setText(
            f'默认：{main or "—"} · 快速：{cfg.get("fastModel") or "—"}'
            if main else '尚无模型')

    @staticmethod
    def _color(hex_str):
        return QColor(hex_str)

    # ---- 动作：Provider ----
    def _new_provider(self):
        dlg = ProviderEditDialog(self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        name, url, key = dlg.values()
        # 新建要求至少 1 个模型：复用添加模型对话框（首个必然=默认模型，隐藏勾选）
        mdlg = AddModelDialog(name, self)
        mdlg.chk_main.hide()
        if mdlg.exec() != mdlg.DialogCode.Accepted:
            return
        model, _ = mdlg.values()
        ok, msg = self.service.add_provider(name, url, key, [model])
        self.status_message.emit(msg, 3000)

    def _edit_provider(self):
        if not self._current:
            return
        cfg = self._providers.get(self._current, {})
        n = len(self.service.models_of(cfg))
        dlg = ProviderEditDialog(self, existing=(self._current, cfg.get('baseUrl', ''),
                                                 cfg.get('apiKey', ''), n))
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        name, url, key = dlg.values()
        ok, msg = self.service.update_provider(self._current, name, url, key)
        if ok and name != self._current:
            self._current = name
        self.status_message.emit(msg, 3000)

    def _delete_provider(self):
        if not self._current:
            return
        name = self._current
        extra = '（它是默认 Provider，删除后自动顺延）' if name == self._default else ''
        if QMessageBox.question(
                self, '删除 Provider',
                f'确认删除 Provider「{name}」？其下所有模型配置将移除，不影响已有会话。{extra}',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        ok, msg = self.service.delete_provider(name)
        self._current = ''
        self.status_message.emit(msg, 3000)

    def _set_default(self):
        if not self._current:
            return
        ok, msg = self.service.set_default(self._current)
        self.status_message.emit(msg, 3000)

    def _toggle_key(self):
        self._key_revealed = not self._key_revealed
        self._render_key(self._providers.get(self._current, {}))

    def _copy_key(self):
        cfg = self._providers.get(self._current, {})
        key = cfg.get('apiKey', '')
        if key:
            QApplication.clipboard().setText(key)
            self.status_message.emit('密钥已复制到剪贴板', 2000)

    def _open_config(self):
        try:
            os.startfile(CC_CONFIG_FILE)
        except Exception:
            self.status_message.emit('配置文件不存在或无法打开', 3000)

    def _new_session_here(self):
        """用此 Provider 新建会话——交回会话面板的向导（带 provider 预置）。"""
        main = self._providers.get(self._current, {}).get('model', '')
        self.new_session_requested.emit(self._current, main)

    # ---- 动作：模型 ----
    def _add_model(self):
        if not self._current:
            return
        dlg = AddModelDialog(self._current, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        model, set_main = dlg.values()
        ok, msg = self.service.add_model(self._current, model, set_main=set_main)
        self.status_message.emit(msg, 3000)

    def _current_model(self):
        it = self.model_tree.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it else ''

    def _rename_model_item(self, item, _col=0):
        old = item.data(0, Qt.ItemDataRole.UserRole)
        dlg = RenameModelDialog(old, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        ok, msg = self.service.rename_model(self._current, old, dlg.value())
        self.status_message.emit(msg, 3000)

    def _show_model_menu(self, pos):
        item = self.model_tree.itemAt(pos)
        if not item or READONLY:
            return
        model = item.data(0, Qt.ItemDataRole.UserRole)
        cfg = self._providers.get(self._current, {})
        menu = FadeMenu(self)
        a_main = menu.addAction('设为默认模型')
        a_fast = menu.addAction('设为快速模型（后台/摘要）')
        a_ren = menu.addAction('重命名')
        menu.addSeparator()
        a_del = menu.addAction('删除')
        a_main.setEnabled(cfg.get('model') != model)
        a_fast.setEnabled(cfg.get('fastModel') != model)
        chosen = menu.exec(self.model_tree.mapToGlobal(pos))
        if chosen == a_main:
            ok, msg = self.service.set_main(self._current, model); self.status_message.emit(msg, 3000)
        elif chosen == a_fast:
            ok, msg = self.service.set_fast(self._current, model); self.status_message.emit(msg, 3000)
        elif chosen == a_ren:
            self._rename_model_item(item)
        elif chosen == a_del:
            ok, msg = self.service.remove_model(self._current, model)
            self.status_message.emit(msg, 3000)

    def _show_provider_menu(self, pos):
        it = self.provider_list.itemAt(pos)
        if not it:
            return
        name = it.data(Qt.ItemDataRole.UserRole)
        self._select_by_name(name)
        menu = FadeMenu(self)
        a_def = menu.addAction('设为默认')
        a_edit = menu.addAction('编辑信息')
        menu.addSeparator()
        a_del = menu.addAction('删除')
        if READONLY:
            for a in (a_def, a_edit, a_del):
                a.setEnabled(False)
        chosen = menu.exec(self.provider_list.mapToGlobal(pos))
        if chosen == a_def:
            ok, msg = self.service.set_default(name); self.status_message.emit(msg, 3000)
        elif chosen == a_edit:
            self._edit_provider()
        elif chosen == a_del:
            self._delete_provider()
