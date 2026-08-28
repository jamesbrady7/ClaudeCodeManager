"""技能模块对话框（view 层）。"""
import os

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QVBoxLayout, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QComboBox, QTextEdit, QToolButton, QScrollArea,
    QPushButton, QDialogButtonBox, QWidget,
)

from ccui.infra.config import ASSETS_DIR
from ccui.app.dialogs import FadeDialog, mk_buttons
from ccui.app.icons import ui_icon, brand_svg_icon
from ccui.skill.data.store import SKILL_CATEGORY_LABELS


class NewSkillDialog(FadeDialog):
    """新建/编辑技能：名称 / 描述 / 类型 / 指令正文。"""

    def __init__(self, parent=None, existing=None, preset_category=''):
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
        cur = (existing.category if existing else preset_category)
        if cur and self.cat_combo.findText(cur) < 0:
            self.cat_combo.addItem(cur)  # 自定义分组也进下拉
        idx = self.cat_combo.findText(cur) if cur else -1
        # 新建默认「其他」（最后一个）/ 预设分组；编辑回填其类型
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


class CategoryDialog(FadeDialog):
    """新建/编辑分组：输入分组名。"""

    def __init__(self, parent=None, title='新建分组', current=''):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(320)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(current)
        self.name_edit.setPlaceholderText('如：前端开发')
        form.addRow('分组名', self.name_edit)
        lay.addLayout(form)
        lay.addWidget(mk_buttons(self, '保存'))

    def name(self):
        return self.name_edit.text().strip()


class GroupIconPicker(FadeDialog):
    """选择分组图标：Lucide 图标库（assets/icons/）+ role-icons SVG。

    返回图标 key：Lucide 名（如 'zap'）或 role-icons 文件名（如 'claude-color.svg'），
    '' 表示清除（用默认）。
    """

    def __init__(self, parent=None, current=''):
        super().__init__(parent)
        self.setWindowTitle('选择分组图标')
        self.resize(560, 430)
        self._chosen = current
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('选择一个图标（Lucide 图标库 + 自定义矢量图）：'))
        scroll = QScrollArea()
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(6)
        keys = []
        icons_dir = os.path.join(ASSETS_DIR, 'icons')
        try:
            keys += sorted(f[:-4] for f in os.listdir(icons_dir) if f.endswith('.svg'))
        except Exception:
            pass
        ri_dir = os.path.join(ASSETS_DIR, 'role-icons')
        try:
            keys += sorted(f for f in os.listdir(ri_dir) if f.lower().endswith('.svg'))
        except Exception:
            pass
        for i, key in enumerate(keys):
            btn = QToolButton()
            btn.setIcon(self._make_icon(key))
            btn.setIconSize(QSize(26, 26))
            btn.setToolTip(key)
            btn.setFixedSize(40, 40)
            if key == current:
                btn.setStyleSheet('border: 2px solid #0a84ff;')
            btn.clicked.connect(lambda _=False, k=key: self._pick(k))
            grid.addWidget(btn, i // 9, i % 9)
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        lay.addWidget(scroll)
        row = QHBoxLayout()
        self.btn_clear = QPushButton('清除图标')
        self.btn_clear.setToolTip('恢复该分组的默认图标')
        self.btn_clear.clicked.connect(lambda: self._pick(''))
        row.addWidget(self.btn_clear)
        row.addStretch(1)
        lay.addLayout(row)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _make_icon(self, key):
        p = os.path.join(ASSETS_DIR, 'icons', f'{key}.svg')
        if os.path.exists(p):
            return ui_icon(key, 24)
        p2 = os.path.join(ASSETS_DIR, 'role-icons', key)
        if os.path.exists(p2):
            return brand_svg_icon(p2, 24)
        return QIcon()

    def _pick(self, key):
        self._chosen = key
        self.accept()

    def chosen(self):
        return self._chosen
