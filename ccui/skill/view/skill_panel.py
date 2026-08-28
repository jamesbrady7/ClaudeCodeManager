"""技能库面板（技能模块 view 层）。

- 左树：按分组浏览，**技能行带勾选框**（批量导出选择，交互与会话表一致——
  勾选框切换选择、点行显示详情）；分组头带图标 + tri-state 全选。
- 右键菜单：分组（编辑分组/新增技能/删除分组）；技能（编辑/删除）。
- 顶部「新建」下拉：新建技能 / 新建分组。
- 引用计数遍历 RoleManager（view 层跨模块 Data 允许）。
"""
import os
import time

from PySide6.QtCore import Qt, QSize, QPoint, QTimer, QFileSystemWatcher, Signal
from PySide6.QtGui import QColor, QBrush, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QLineEdit, QDialog, QFrame, QPlainTextEdit, QMenu,
    QApplication, QInputDialog, QMessageBox, QFileDialog,
)

from ccui.infra.config import SKILLS_DIR, ROLES_DIR, READONLY, ASSETS_DIR
from ccui.infra.signalhub import SignalHub
from ccui.role.data.manager import RoleManager  # 引用计数在 view 层跨模块（隔离规则允许）
from ccui.skill.service.skill_service import SkillService
from ccui.skill.view.dialogs import NewSkillDialog, CategoryDialog, GroupIconPicker
from ccui.app.theme import COLOR_MUTED
from ccui.app.icons import ui_icon, brand_svg_icon
from ccui.app.widgets import PressButton, FadeMenu

CATEGORY_ICONS = {
    '动效动画': 'zap', '界面设计': 'palette', '设计系统': 'layers',
    '品牌视觉': 'star', '内容演示': 'presentation', '综合': 'layout-grid', '其他': 'folder',
}


class SkillPanel(QWidget):
    status_message = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.skill_service = SkillService()
        self._skills = []
        self._current = None
        self._suppress = False
        self._changed_at = 0
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
        # 「新建」下拉：新建技能 / 新建分组
        self.btn_new = PressButton(' 新建  ▾')
        self.btn_new.setObjectName('btnNew')
        self.btn_new.setIcon(ui_icon('plus', 14, '#ffffff'))
        self.btn_new.clicked.connect(self._show_new_menu)  # 手动弹菜单，避免 setMenu 的默认指示器
        tb.addWidget(self.btn_new)
        self.btn_refresh = QPushButton('刷新')
        self.btn_refresh.clicked.connect(self._reload)
        tb.addWidget(self.btn_refresh)
        self.btn_export = QPushButton(' 导出')
        self.btn_export.setIcon(ui_icon('download', 14))
        self.btn_export.setToolTip('导出勾选的技能（批量）为 zip')
        self.btn_export.clicked.connect(self._export_checked)
        tb.addWidget(self.btn_export)
        self.btn_import = QPushButton(' 导入')
        self.btn_import.setIcon(ui_icon('upload', 14))
        self.btn_import.setToolTip('从 zip 导入技能（支持含多个技能）')
        self.btn_import.clicked.connect(self._import_skill)
        self.btn_import.setEnabled(not READONLY)
        tb.addWidget(self.btn_import)
        tb.addStretch(1)
        self.lbl_stats = QLabel('')
        self.lbl_stats.setObjectName('totals')
        tb.addWidget(self.lbl_stats)
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText('搜索技能名 / 描述…')
        self.edit_search.setMaximumWidth(220)
        self.edit_search.setClearButtonEnabled(True)
        self.edit_search.addAction(ui_icon('search', 14),
                                   QLineEdit.ActionPosition.LeadingPosition)
        self.edit_search.textChanged.connect(self._schedule_reload)  # 防抖：打字不逐键重建
        tb.addWidget(self.edit_search)
        root.addWidget(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setObjectName('skillGroupTree')
        self.tree.setColumnCount(1)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)   # 分支箭头（分组收起/展开，独立可点）
        self.tree.setIndentation(16)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_menu)
        splitter.addWidget(self.tree)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(4, 8, 8, 8)
        self.lbl_name = QLabel('选择左侧技能')
        self.lbl_name.setStyleSheet('font-size: 20px; font-weight: 600; color: #f5f5f7;')
        right_lay.addWidget(self.lbl_name)
        meta_row = QHBoxLayout()
        self.lbl_meta = QLabel('')
        self.lbl_meta.setStyleSheet(f'color: {COLOR_MUTED};')
        meta_row.addWidget(self.lbl_meta, 1)
        self.btn_copy_uuid = QPushButton('复制 uuid')
        self.btn_copy_uuid.setObjectName('btnResume')
        self.btn_copy_uuid.clicked.connect(self._copy_uuid)
        meta_row.addWidget(self.btn_copy_uuid)
        right_lay.addLayout(meta_row)
        self.lbl_refs = QLabel('')
        self.lbl_refs.setStyleSheet(f'color: {COLOR_MUTED};')
        right_lay.addWidget(self.lbl_refs)
        right_lay.addSpacing(6)
        right_lay.addWidget(QLabel('描述：'))
        self.lbl_desc = QLabel('')
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet('color: #d4d4d8;')
        right_lay.addWidget(self.lbl_desc)
        right_lay.addWidget(QLabel('指令正文：'))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        right_lay.addWidget(self.preview, 1)
        btn_row = QHBoxLayout()
        self.btn_edit = QPushButton('编辑')
        self.btn_edit.clicked.connect(self._edit_current)
        self.btn_rename = QPushButton('重命名')
        self.btn_rename.clicked.connect(self._rename_current)
        self.btn_delete = QPushButton('删除')
        self.btn_delete.setProperty('danger', True)
        self.btn_delete.clicked.connect(self._delete_current)
        btn_row.addWidget(self.btn_edit)
        btn_row.addWidget(self.btn_rename)
        btn_row.addWidget(self.btn_delete)
        btn_row.addStretch(1)
        right_lay.addLayout(btn_row)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)  # splitter 吃满剩余，工具栏保持内容高度

    def _setup_watcher(self):
        self.watcher = QFileSystemWatcher(self)
        for p in (SKILLS_DIR, ROLES_DIR):
            if os.path.exists(p):
                self.watcher.addPath(p)
        self.watcher.directoryChanged.connect(self._schedule_reload)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(400)
        self.debounce.timeout.connect(self._reload)
        hub = SignalHub.instance()
        hub.subscribe('skills.changed', self._schedule_reload)
        hub.subscribe('roles.changed', self._schedule_reload)

    def _schedule_reload(self, *_):
        self.debounce.start()

    # ---- 渲染 ----
    def _reload(self):
        skills = self.skill_service.list_skills()
        q = self.edit_search.text().strip().lower()
        if q:
            skills = [s for s in skills
                      if q in s.name.lower() or q in (s.description or '').lower()]
        self._skills = skills
        self._refs = self._ref_map()
        groups = {}
        for s in skills:
            groups.setdefault(s.category or '其他', []).append(s)
        ordered = [c for c in self.skill_service.list_categories() if c in groups]
        ordered += [c for c in groups if c not in ordered]
        ordered += [c for c in self.skill_service.list_categories() if c not in groups]  # 空分组也显示
        self.tree.blockSignals(True)
        self.tree.clear()
        for cat in ordered:
            items = groups.get(cat, [])
            header = QTreeWidgetItem([f'{cat}   ·   {len(items)}'])
            header.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            header.setData(0, Qt.ItemDataRole.UserRole, cat)
            header.setIcon(0, self._render_group_icon(cat, 14))
            f = header.font(0)
            f.setBold(True)
            header.setFont(0, f)
            header.setForeground(0, QColor(COLOR_MUTED))
            header.setBackground(0, QBrush(QColor('#2b2b30')))
            header.setSizeHint(0, QSize(0, 28))
            header.setCheckState(0, Qt.CheckState.Unchecked)
            self.tree.addTopLevelItem(header)
            for s in items:
                n_refs = len(self._refs.get(s.uuid, []))
                label = s.name
                if s.description:
                    label += f'   —   {s.description[:44]}'
                if n_refs:
                    label += f'   ·  {n_refs} 角色'
                item = QTreeWidgetItem([label])
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                              | Qt.ItemFlag.ItemIsUserCheckable)
                item.setData(0, Qt.ItemDataRole.UserRole, s.name)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                item.setForeground(0, QColor('#d4d4d8'))
                item.setToolTip(0, f'{s.name}\n{s.description}\nuuid: {s.uuid}')
                header.addChild(item)
        self.tree.blockSignals(False)
        self.tree.expandAll()
        self._update_stats()
        if self._current and self._current.name not in [s.name for s in skills]:
            self._show_detail(None)

    def _update_stats(self):
        total = len(self._skills)
        checked = sum(1 for i in range(self.tree.topLevelItemCount())
                      for j in range(self.tree.topLevelItem(i).childCount())
                      if self.tree.topLevelItem(i).child(j).checkState(0) == Qt.CheckState.Checked)
        self.lbl_stats.setText(f'{total} 个技能' + (f' · 已选 {checked}' if checked else ''))

    def _checked_names(self):
        out = []
        for i in range(self.tree.topLevelItemCount()):
            h = self.tree.topLevelItem(i)
            for j in range(h.childCount()):
                if h.child(j).checkState(0) == Qt.CheckState.Checked:
                    out.append(h.child(j).data(0, Qt.ItemDataRole.UserRole))
        return out

    # ---- 树交互 ----
    def _toggle_group(self, header):
        n = header.childCount()
        if n == 0:
            return
        checked = sum(1 for i in range(n)
                      if header.child(i).checkState(0) == Qt.CheckState.Checked)
        new_state = (Qt.CheckState.Unchecked if checked == n else Qt.CheckState.Checked)
        self._suppress = True
        for i in range(n):
            header.child(i).setCheckState(0, new_state)
        self._suppress = False
        self._update_header_state(header)
        self._update_stats()

    def _update_header_state(self, header):
        n = header.childCount()
        checked = sum(1 for i in range(n)
                      if header.child(i).checkState(0) == Qt.CheckState.Checked)
        state = (Qt.CheckState.Checked if checked == n
                 else Qt.CheckState.Unchecked if checked == 0 else Qt.CheckState.PartiallyChecked)
        self._suppress = True
        header.setCheckState(0, state)
        self._suppress = False

    def _on_item_clicked(self, item, column):
        if item.parent() is None:
            # 分组头：勾选框点击走 itemChanged 全选；行点击 = 折叠/展开（无延迟）
            if time.time() - self._changed_at < 0.1:
                return
            if item.isExpanded():
                self.tree.collapseItem(item)
            else:
                self.tree.expandItem(item)
            return
        if time.time() - self._changed_at < 0.1:
            return  # 勾选框点击，不显示详情
        name = item.data(0, Qt.ItemDataRole.UserRole)
        self._show_detail(self.skill_service.get_skill(name))

    def _on_item_double_clicked(self, item, column):
        if item.parent() is not None:
            self._edit_current()  # 技能行双击 → 编辑
        # 分组头双击：Qt 默认收起/展开，不做编辑、不触发全选（行点击只折叠）

    def _on_item_changed(self, item, column):
        if self._suppress:
            return
        self._changed_at = time.time()
        if item.parent() is None:
            # 分组头勾选框：全选/全不选其下技能（勾选框是唯一的全选入口）
            checked = item.checkState(0) == Qt.CheckState.Checked
            self._suppress = True
            for i in range(item.childCount()):
                item.child(i).setCheckState(0,
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self._suppress = False
        else:
            self._update_header_state(item.parent())
        self._update_stats()

    def _ref_map(self):
        """uuid → 引用该技能的角色名列表（遍历 RoleManager，view 层跨模块）。"""
        m = {}
        for r in RoleManager.instance().roles():
            for u in r.skills:
                if u:
                    m.setdefault(u, []).append(r.name)
        return m

    def _render_group_icon(self, cat, size=14):
        """分组图标：优先用户配置的图标 key，其次 CATEGORY_ICONS 默认，最后 folder。"""
        key = self.skill_service.get_category_icon(cat) or CATEGORY_ICONS.get(cat, 'folder')
        p = os.path.join(ASSETS_DIR, 'icons', f'{key}.svg')
        if os.path.exists(p):
            return ui_icon(key, size)
        p2 = os.path.join(ASSETS_DIR, 'role-icons', key)
        if os.path.exists(p2):
            return brand_svg_icon(p2, size)
        return ui_icon('folder', size)

    def _set_category_icon(self, cat):
        dlg = GroupIconPicker(self, current=self.skill_service.get_category_icon(cat))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.skill_service.set_category_icon(cat, dlg.chosen())
            self.status_message.emit(f'分组「{cat}」图标已更新', 2000)
            self._reload()

    def _show_detail(self, skill):
        self._current = skill
        if not skill:
            self.lbl_name.setText('选择左侧技能')
            self.lbl_meta.setText('')
            self.lbl_refs.setText('')
            self.lbl_desc.setText('')
            self.preview.setPlainText('')
            for b in (self.btn_edit, self.btn_rename, self.btn_delete, self.btn_copy_uuid):
                b.setEnabled(False)
            return
        self.lbl_name.setText(skill.name)
        self.lbl_meta.setText(f'{skill.category}    ·    {skill.uuid}')
        ref_names = self._refs.get(skill.uuid, [])
        self.lbl_refs.setText(f'被 {len(ref_names)} 个角色引用'
                              + (f'：{"、".join(ref_names)}' if ref_names else ''))
        self.lbl_desc.setText(skill.description or '（无描述）')
        self.preview.setPlainText(skill.body or '')
        for b in (self.btn_edit, self.btn_rename, self.btn_delete, self.btn_copy_uuid):
            b.setEnabled(True)

    def _copy_uuid(self):
        if self._current:
            QApplication.clipboard().setText(self._current.uuid)
            self.status_message.emit('技能 uuid 已复制', 2000)

    # ---- 新建下拉（手动弹菜单，只有一个 ▾ 箭头）----
    def _show_new_menu(self):
        menu = QMenu(self)
        act_skill = menu.addAction(ui_icon('wrench', 15), '新建技能')
        act_cat = menu.addAction(ui_icon('folder', 15), '新建分组')
        chosen = menu.exec(self.btn_new.mapToGlobal(QPoint(0, self.btn_new.height())))
        if chosen == act_skill:
            self._new_skill()
        elif chosen == act_cat:
            self._new_category()

    def _new_skill(self, preset_category=''):
        dlg = NewSkillDialog(self, preset_category=preset_category)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name, desc, body, cat = dlg.values()
            if not name:
                return
            r = self.skill_service.create_skill(name, desc, body, category=cat)
            if r.get('ok'):
                self.status_message.emit(f'技能 {name} 已创建', 3000)
                self.edit_search.clear()
                self._reload()
            else:
                QMessageBox.warning(self, '创建失败', r.get('error', ''))

    def _new_category(self):
        dlg = CategoryDialog(self, title='新建分组')
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name = dlg.name()
            if not name:
                return
            self.skill_service.add_category(name)
            self.status_message.emit(f'分组「{name}」已创建', 3000)
            self._reload()

    def _rename_category(self, cat):
        dlg = CategoryDialog(self, title='编辑分组', current=cat)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new = dlg.name()
            if not new or new == cat:
                return
            self.skill_service.rename_category(cat, new)
            self.status_message.emit(f'分组已重命名为「{new}」', 3000)
            self._reload()

    def _delete_category(self, cat):
        if QMessageBox.question(self, '删除分组',
                                f'确定删除分组「{cat}」？\n该分组下的技能将移到「其他」。',
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.skill_service.delete_category(cat)
        self.status_message.emit(f'分组「{cat}」已删除', 3000)
        self._reload()

    # ---- 技能动作 ----
    def _edit_current(self):
        if not self._current:
            return
        dlg = NewSkillDialog(self, existing=self._current)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            _, desc, body, cat = dlg.values()
            self.skill_service.update_skill(self._current.name, desc, body, cat)
            self.status_message.emit('技能已更新', 3000)
            self._reload()
            self._show_detail(self.skill_service.get_skill(self._current.name))

    def _rename_current(self):
        if not self._current:
            return
        new, ok = QInputDialog.getText(self, '重命名技能',
                                       f'把 "{self._current.name}" 重命名为：',
                                       text=self._current.name)
        if ok and new and new != self._current.name:
            r = self.skill_service.rename_skill(self._current.name, new.strip())
            if r.get('ok'):
                self.status_message.emit(f'技能已重命名为 {new.strip()}', 3000)
                self._reload()
            else:
                QMessageBox.warning(self, '重命名失败', r.get('error', ''))

    def _delete_current(self):
        if not self._current:
            return
        refs = self._refs.get(self._current.uuid, [])
        msg = f'确定删除技能「{self._current.name}」？'
        if refs:
            msg += (f'\n\n该技能正被 {len(refs)} 个角色引用：{"、".join(refs)}'
                    '\n删除后这些角色将缺失该技能（角色 meta 保留 uuid，会话启动时优雅跳过）。')
        if QMessageBox.question(self, '删除技能', msg,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.skill_service.delete_skill(self._current.name)
        self.status_message.emit(f'技能 {self._current.name} 已删除', 3000)
        self._show_detail(None)
        self._reload()

    # ---- 导入 / 导出 ----
    def _export_checked(self):
        names = self._checked_names()
        if not names and self._current:
            names = [self._current.name]
        if not names:
            self.status_message.emit('先勾选要导出的技能', 3000)
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出技能',
                                              'skills-export.zip', 'Zip 档案 (*.zip)')
        if not path:
            return
        res = self.skill_service.export_skills(names, path)
        if res.get('ok'):
            self.status_message.emit(f"已导出 {len(res['exported'])} 个技能", 3000)
        else:
            QMessageBox.warning(self, '导出失败', res.get('error', ''))

    def _import_skill(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入技能', '', 'Zip 档案 (*.zip)')
        if not path:
            return
        res = self.skill_service.import_skill(path, mode='skip')
        if (not res.get('ok') and res.get('conflicts')) or res.get('conflicts'):
            # 有冲突 → 询问处理方式
            n_conf = len(res.get('conflicts', []))
            box = QMessageBox(self)
            box.setWindowTitle('技能已存在')
            box.setText(f'导入包里有 {n_conf} 个技能已存在（同名或同 uuid），如何处理？')
            b_over = box.addButton('覆盖', QMessageBox.ButtonRole.AcceptRole)
            b_new = box.addButton('换新 uuid', QMessageBox.ButtonRole.AcceptRole)
            b_skip = box.addButton('跳过', QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked == b_skip:
                return
            mode = 'overwrite' if clicked == b_over else 'new_uuid'
            res = self.skill_service.import_skill(path, mode=mode)
        if not res.get('ok'):
            QMessageBox.warning(self, '导入失败', res.get('error', '未知错误'))
            return
        n = len(res.get('imported', []))
        self.status_message.emit(f'已导入 {n} 个技能', 3000)
        self._reload()

    # ---- 右键菜单 ----
    def _show_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        menu = FadeMenu(self)
        if item.parent() is None:
            # 分组头
            cat = item.data(0, Qt.ItemDataRole.UserRole)
            act_edit = menu.addAction(ui_icon('settings', 15), '编辑分组')
            act_icon = menu.addAction(ui_icon('image', 15), '设置图标')
            act_add = menu.addAction(ui_icon('plus', 15), '新增技能')
            act_del = menu.addAction(ui_icon('trash-2', 15, '#ff6961'), '删除分组')
            chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
            if chosen == act_edit:
                self._rename_category(cat)
            elif chosen == act_icon:
                self._set_category_icon(cat)
            elif chosen == act_add:
                self._new_skill(preset_category=cat)
            elif chosen == act_del:
                self._delete_category(cat)
        else:
            name = item.data(0, Qt.ItemDataRole.UserRole)
            self._show_detail(self.skill_service.get_skill(name))
            act_edit = menu.addAction(ui_icon('settings', 15), '编辑')
            act_del = menu.addAction(ui_icon('trash-2', 15, '#ff6961'), '删除')
            chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
            if chosen == act_edit:
                self._edit_current()
            elif chosen == act_del:
                self._delete_current()
