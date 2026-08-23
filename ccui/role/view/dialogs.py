"""角色模块对话框（view 层）。"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton,
    QDialogButtonBox, QListWidget, QListWidgetItem,
    QMessageBox, QTextEdit, QTreeWidget, QTreeWidgetItem,
)

from ccui.role.service.role_service import RoleService


class NewRoleDialog(QDialog):
    """新建角色：名称 / 描述 / 勾选技能。"""

    def __init__(self, skills, parent=None):
        super().__init__(parent)
        self.setWindowTitle('新建角色')
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText('字母/数字/_/-（如 uidesigner）')
        form.addRow('名称', self.name_edit)
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText('如：UI 设计师')
        form.addRow('描述', self.desc_edit)
        lay.addLayout(form)
        lay.addWidget(QLabel('技能：'))
        self.skill_list = QListWidget()
        for s in skills:
            item = QListWidgetItem(f"{s.name}（{s.description}）")
            item.setData(Qt.ItemDataRole.UserRole, s.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.skill_list.addItem(item)
        lay.addWidget(self.skill_list)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('创建')
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def name(self):
        return self.name_edit.text().strip()

    def description(self):
        return self.desc_edit.text().strip()

    def selected_skills(self):
        return [self.skill_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.skill_list.count())
                if self.skill_list.item(i).checkState() == Qt.CheckState.Checked]


class KnowledgeDialog(QDialog):
    """编辑角色知识库。"""

    def __init__(self, title, content, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'编辑知识库：{title}')
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        self.edit = QTextEdit()
        self.edit.setPlainText(content)
        lay.addWidget(self.edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('保存')
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def content(self):
        return self.edit.toPlainText()


class SkillsDialog(QDialog):
    """管理角色的技能：勾选分配/取消，新建技能、编辑选中技能。"""

    def __init__(self, role_name, all_skills, assigned, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'管理技能：{role_name}')
        self.role_name = role_name
        self.service = RoleService()
        self.resize(520, 440)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('勾选分配给该角色的技能：'))
        self.list = QListWidget()
        for s in all_skills:
            label = f"{s.name}（{s.description}）" + (" [角色专属]" if s.source == 'role' else "")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, s.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if s.name in assigned else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        self.btn_new = QPushButton('新建技能')
        self.btn_new.clicked.connect(self._new_skill)
        self.btn_edit = QPushButton('编辑选中技能')
        self.btn_edit.clicked.connect(self._edit_skill)
        row.addWidget(self.btn_new)
        row.addWidget(self.btn_edit)
        row.addStretch(1)
        lay.addLayout(row)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('保存')
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _selected_skill(self):
        it = self.list.currentItem()
        return it.data(0x0100) if it else None

    def _new_skill(self):
        dlg = NewSkillDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name, desc, body = dlg.values()
            if not name:
                return
            self.service.create_skill(name, desc, body)
            item = QListWidgetItem(f"{name}（{desc}）")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(item)
            self.list.setCurrentItem(item)

    def _edit_skill(self):
        name = self._selected_skill()
        if not name:
            return
        skill = self.service.get_skill(name)
        if not skill:
            QMessageBox.warning(self, '未找到', f'技能 {name} 不存在')
            return
        dlg = NewSkillDialog(self, existing=skill)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            _, desc, body = dlg.values()
            self.service.write_skill(name, f'---\nname: {name}\ndescription: {desc}\n---\n\n{body}'.strip() + '\n')
            self.list.currentItem().setText(f"{name}（{desc}）")

    def selected_skills(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]


class NewSkillDialog(QDialog):
    """新建/编辑技能：名称 / 描述 / 指令正文。"""

    def __init__(self, parent=None, existing=None):
        super().__init__(parent)
        self.setWindowTitle('新建技能' if not existing else f'编辑技能：{existing.name}')
        self.resize(480, 380)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(existing.name if existing else '')
        self.name_edit.setPlaceholderText('如 apple-ui')
        form.addRow('名称', self.name_edit)
        self.desc_edit = QLineEdit(existing.description if existing else '')
        self.desc_edit.setPlaceholderText('如：Apple/macOS 设计规范')
        form.addRow('描述', self.desc_edit)
        lay.addLayout(form)
        lay.addWidget(QLabel('指令正文（模型相关工作时遵循）：'))
        self.body_edit = QTextEdit()
        self.body_edit.setPlainText(existing.body if existing else '')
        lay.addWidget(self.body_edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('保存')
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def values(self):
        return (self.name_edit.text().strip(), self.desc_edit.text().strip(), self.body_edit.toPlainText())
