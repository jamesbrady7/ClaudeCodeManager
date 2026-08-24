"""角色模块对话框（view 层）。"""
import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QWidget, QToolButton, QScrollArea,
    QDialogButtonBox, QDialog,
    QMessageBox, QTextEdit, QFileDialog,
    QComboBox,
)

from ccui.role.service.role_service import RoleService
from ccui.role.data.store import SKILL_CATEGORY_LABELS
from ccui.app.dialogs import FadeDialog, mk_buttons
from ccui.app.theme import ASSETS_DIR
from ccui.app.icons import role_avatar
from ccui.app.widgets import SkillGroupList


class NewRoleDialog(FadeDialog):
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
        lay.addWidget(QLabel('技能（点击分类行全选/全不选）：'))
        self.skill_list = SkillGroupList(skills, checked_names=(), category_order=SKILL_CATEGORY_LABELS)
        lay.addWidget(self.skill_list)
        lay.addWidget(mk_buttons(self, '创建'))

    def name(self):
        return self.name_edit.text().strip()

    def description(self):
        return self.desc_edit.text().strip()

    def selected_skills(self):
        return self.skill_list.selected_skills()


class KnowledgeDialog(FadeDialog):
    """编辑角色知识库。"""

    def __init__(self, title, content, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'编辑知识库：{title}')
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        self.edit = QTextEdit()
        self.edit.setPlainText(content)
        lay.addWidget(self.edit)
        lay.addWidget(mk_buttons(self, '保存'))

    def content(self):
        return self.edit.toPlainText()


class SkillsDialog(FadeDialog):
    """管理角色的技能：按类型分组勾选分配/取消，新建技能、编辑选中技能。"""

    def __init__(self, role_name, all_skills, assigned, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'管理技能：{role_name}')
        self.role_name = role_name
        self.service = RoleService()
        self.resize(560, 480)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('勾选分配给该角色的技能（点勾选框切换 · 双击技能行可编辑）：'))
        self.list = SkillGroupList(all_skills, checked_names=assigned,
                                   category_order=SKILL_CATEGORY_LABELS,
                                   row_select_toggles=False)
        self.list.doubleClickedSkill.connect(self._edit_skill_named)
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
        lay.addWidget(mk_buttons(self, '保存'))

    def _reload(self):
        """保留勾选态，从磁盘重建分组列表（新建/编辑技能后调用）。"""
        checked = self.list.selected_skills()
        self.list.rebuild(self.service.list_skills(self.role_name), checked,
                          SKILL_CATEGORY_LABELS)

    def _select_skill(self, name):
        it = self.list.find_item(name)
        if it:
            self.list.setCurrentItem(it)
            self.list.scrollToItem(it)

    def _new_skill(self):
        dlg = NewSkillDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name, desc, body, cat = dlg.values()
            if not name:
                return
            self.service.create_skill(name, desc, body, category=cat)
            self._reload()
            self._select_skill(name)

    def _edit_skill(self):
        self._edit_skill_named(self.list.current_skill_name())

    def _edit_skill_named(self, name):
        if not name:
            return
        skill = self.service.get_skill(name)
        if not skill:
            QMessageBox.warning(self, '未找到', f'技能 {name} 不存在')
            return
        dlg = NewSkillDialog(self, existing=skill)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            _, desc, body, cat = dlg.values()
            content = (f'---\nname: {name}\ncategory: {cat}\n'
                       f'description: {desc}\n---\n\n{body}').strip() + '\n'
            self.service.write_skill(name, content)
            self._reload()
            self._select_skill(name)

    def selected_skills(self):
        return self.list.selected_skills()


class NewSkillDialog(FadeDialog):
    """新建/编辑技能：名称 / 描述 / 类型 / 指令正文。"""

    def __init__(self, parent=None, existing=None):
        super().__init__(parent)
        self.setWindowTitle('新建技能' if not existing else f'编辑技能：{existing.name}')
        self.resize(480, 400)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(existing.name if existing else '')
        self.name_edit.setPlaceholderText('如 apple-ui')
        form.addRow('名称', self.name_edit)
        self.desc_edit = QLineEdit(existing.description if existing else '')
        self.desc_edit.setPlaceholderText('如：Apple/macOS 设计规范')
        form.addRow('描述', self.desc_edit)
        self.cat_combo = QComboBox()
        self.cat_combo.addItems(SKILL_CATEGORY_LABELS)
        cur = (existing.category if existing else '')
        idx = self.cat_combo.findText(cur) if cur else -1
        # 新建默认「其他」（最后一个）；编辑则回填其类型
        self.cat_combo.setCurrentIndex(idx if idx >= 0 else len(SKILL_CATEGORY_LABELS) - 1)
        self.cat_combo.setToolTip('类型：技能在管理窗体中按此分组')
        form.addRow('类型', self.cat_combo)
        lay.addLayout(form)
        lay.addWidget(QLabel('指令正文（模型相关工作时遵循）：'))
        self.body_edit = QTextEdit()
        self.body_edit.setPlainText(existing.body if existing else '')
        lay.addWidget(self.body_edit)
        lay.addWidget(mk_buttons(self, '保存'))

    def values(self):
        return (self.name_edit.text().strip(),
                self.desc_edit.text().strip(),
                self.body_edit.toPlainText(),
                self.cat_combo.currentText())


class IconPickerDialog(FadeDialog):
    """从 assets/role-icons/ 网格选择角色头像，或上传本地图片。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('选择角色图标')
        self.resize(560, 420)
        self._chosen = ''
        lay = QVBoxLayout(self)
        icons_dir = os.path.join(ASSETS_DIR, 'role-icons')
        files = []
        if os.path.isdir(icons_dir):
            files = sorted(f for f in os.listdir(icons_dir)
                           if f.lower().endswith(('.svg', '.png', '.jpg', '.jpeg', '.ico', '.webp')))
        if not files:
            hint = QLabel(f'图标库为空。\n把矢量图（SVG/PNG）放到：\n{icons_dir}\n然后重新打开本窗口。')
            hint.setWordWrap(True)
            lay.addWidget(hint)
        else:
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(8, 8, 8, 8)
            grid.setSpacing(6)
            for i, f in enumerate(files):
                path = os.path.join(icons_dir, f)
                btn = QToolButton()
                btn.setIcon(QIcon(path))
                btn.setIconSize(QSize(40, 40))
                btn.setToolTip(f)
                btn.setFixedSize(52, 52)
                btn.clicked.connect(lambda _=False, p=path: self._pick(p))
                grid.addWidget(btn, i // 8, i % 8)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(grid_host)
            lay.addWidget(scroll)
        row = QHBoxLayout()
        self.btn_upload = QPushButton('上传本地图片…')
        self.btn_upload.clicked.connect(self._upload)
        row.addWidget(self.btn_upload)
        row.addStretch(1)
        lay.addLayout(row)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _pick(self, path):
        self._chosen = path
        self.accept()

    def _upload(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择图片', '',
                                              '图片 (*.png *.jpg *.jpeg *.svg *.ico *.webp)')
        if path:
            self._chosen = path
            self.accept()

    def chosen(self):
        return self._chosen


class EditRoleDialog(FadeDialog):
    """编辑角色信息：名称 / 描述 / 图标（从库选择或上传）。"""

    def __init__(self, role, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'编辑角色：{role.name}')
        self._role_name = role.name
        self._icon_path = role.icon or ''
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(role.name)
        self.name_edit.setPlaceholderText('字母/数字/_/-（如 uidesigner）')
        form.addRow('名称', self.name_edit)
        icon_row = QHBoxLayout()
        self.lbl_icon_preview = QLabel()
        self.lbl_icon_preview.setFixedSize(34, 34)
        self._refresh_preview()
        icon_row.addWidget(self.lbl_icon_preview)
        self.btn_change_icon = QPushButton('更换图标…')
        self.btn_change_icon.clicked.connect(self._pick_icon)
        icon_row.addWidget(self.btn_change_icon)
        icon_row.addStretch(1)
        form.addRow('图标', icon_row)
        lay.addLayout(form)
        # 描述放最下面，用大文本框（描述通常较长）
        lay.addWidget(QLabel('描述：'))
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlainText(role.description or '')
        self.desc_edit.setPlaceholderText('角色的职责 / 专长 / 风格等（支持多行）')
        self.desc_edit.setFixedHeight(110)
        lay.addWidget(self.desc_edit)
        lay.addWidget(mk_buttons(self, '保存'))

    def _refresh_preview(self):
        self.lbl_icon_preview.setPixmap(
            role_avatar(self._role_name, self._icon_path).pixmap(34, 34))

    def _pick_icon(self):
        dlg = IconPickerDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.chosen():
            self._icon_path = dlg.chosen()
            self._refresh_preview()

    def name(self):
        return self.name_edit.text().strip()

    def description(self):
        return self.desc_edit.toPlainText().strip()

    def icon(self):
        return self._icon_path
