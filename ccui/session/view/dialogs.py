"""会话模块对话框（view 层）。"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QRadioButton,
    QDialogButtonBox, QComboBox, QFileDialog, QTreeWidget, QTreeWidgetItem,
)

from ccui.app.theme import fmt_size


class ResumeDialog(QDialog):
    """恢复会话：选择权限模式 + Provider（默认 = 该会话上次的）。"""

    def __init__(self, default_mode, title_hint, providers, default_provider, parent=None):
        super().__init__(parent)
        self.setWindowTitle('恢复会话')
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        hint = QLabel(f'会话「{title_hint}」上次使用的权限模式：'
                      f'{"危险模式" if default_mode == "danger" else "正常模式"}')
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.rb_normal = QRadioButton('正常模式')
        self.rb_danger = QRadioButton('危险模式（跳过权限确认）')
        if default_mode == 'danger':
            self.rb_danger.setChecked(True)
        else:
            self.rb_normal.setChecked(True)
        lay.addWidget(self.rb_normal)
        lay.addWidget(self.rb_danger)
        prov_row = QHBoxLayout()
        prov_row.addWidget(QLabel('Provider:'))
        self.cb_provider = QComboBox()
        self.cb_provider.addItems(providers if providers else ['(无)'])
        if default_provider and default_provider in providers:
            self.cb_provider.setCurrentIndex(providers.index(default_provider))
        prov_row.addWidget(self.cb_provider, 1)
        lay.addLayout(prov_row)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('恢复')
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def mode(self):
        return 'danger' if self.rb_danger.isChecked() else 'normal'

    def provider(self):
        return self.cb_provider.currentText()


class NewSessionDialog(QDialog):
    """新建会话：工作目录（原生选择器）+ Provider + 可选继承会话。"""

    def __init__(self, providers, default_provider, last_cwd, parent=None, sessions=None):
        super().__init__(parent)
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
        self.cb_provider.addItems(providers if providers else ['(无)'])
        if default_provider and default_provider in providers:
            self.cb_provider.setCurrentIndex(providers.index(default_provider))
        form.addRow('Provider', self.cb_provider)
        inherit_row = QHBoxLayout()
        self.lbl_inherit = QLabel('未选择')
        inherit_row.addWidget(self.lbl_inherit, 1)
        self.btn_inherit = QPushButton('选择继承会话…')
        self.btn_inherit.clicked.connect(self._pick_inherit)
        inherit_row.addWidget(self.btn_inherit)
        form.addRow('继承会话', inherit_row)
        lay.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('创建并启动')
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

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

    def provider(self):
        return self.cb_provider.currentText()

    def inherit_ids(self):
        return list(self._inherit_ids)


class InheritDialog(QDialog):
    """选择要继承的会话（可多选；勾选 0 个 = 不继承）。

    角色「创建角色会话」与会话模块「新建会话」复用；通过 title/ok_text/hint 调整文案。
    """

    def __init__(self, sessions, parent=None, title='选择要继承的会话',
                 ok_text='开始继承会话', hint=''):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 380)
        lay = QVBoxLayout(self)
        if hint:
            h = QLabel(hint)
            h.setWordWrap(True)
            lay.addWidget(h)
        self.list = QTreeWidget()
        self.list.setHeaderLabels(['会话', '时间'])
        self.list.setRootIsDecorated(False)
        for s in sessions:
            if s.isLive:
                continue
            item = QTreeWidgetItem([s.title or '(空会话)', ''])
            item.setData(0, Qt.ItemDataRole.UserRole, s.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            self.list.addTopLevelItem(item)
        lay.addWidget(self.list)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def selected_ids(self):
        return [self.list.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                for i in range(self.list.topLevelItemCount())
                if self.list.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]


class DeleteDialog(QDialog):
    """删除确认：列出会话 + 释放大小。"""

    def __init__(self, items, total_size, parent=None):
        super().__init__(parent)
        self.setWindowTitle('确认删除')
        self.resize(480, 320)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f'确认删除 {len(items)} 个会话？将释放约 {fmt_size(total_size)}：'))
        lst = QTreeWidget(self)
        lst.setHeaderLabels(['会话', '项目'])
        lst.setRootIsDecorated(False)
        for title, proj in items:
            lst.addTopLevelItem(QTreeWidgetItem([title, proj]))
        lay.addWidget(lst)
        warn = QLabel('⚠ 运行中的会话不会被删除（已自动排除）')
        warn.setStyleSheet('color:#f14c4c;')
        lay.addWidget(warn)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('确认删除')
        btns.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet(
            'background:rgba(255,69,58,.2);color:#ff6961;border:1px solid rgba(255,69,58,.4);border-radius:8px;padding:6px 16px;')
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
