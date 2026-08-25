"""会话模块独立面板（view 层）：会话列表 UI + 事件 → 调 SessionService。

通过 status_message 信号把状态消息发给宿主窗口（MainWindow 的 statusBar）。
"""
import math
import os
import time
import traceback

from PySide6.QtCore import Qt, QSize, QTimer, QPropertyAnimation, QEasingCurve, QFileSystemWatcher, Signal
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QLineEdit, QDialog, QFileDialog, QMessageBox,
    QAbstractItemView, QHeaderView, QFrame, QGraphicsOpacityEffect, QStyledItemDelegate,
    QApplication,
)

LIVE_ROLE = Qt.ItemDataRole.UserRole + 5  # 标记 LIVE 行（delegate 画底衬）


class LiveRowDelegate(QStyledItemDelegate):
    """LIVE 行浅红底衬：画在 base paint 之上（QSS 背景覆盖不了 setBackground，故用此）。"""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        # 查第 0 列的 LIVE 标记（每列单元格都整行铺红底衬）
        if index.siblingAtColumn(0).data(LIVE_ROLE):
            painter.fillRect(option.rect, QColor(255, 69, 58, 24))

from ccui.infra.config import PROJECTS, SESSIONS_DIR, HISTORY, CLAUDE_JSON, READONLY, log
from ccui.infra.signalhub import SignalHub
from ccui.infra.utils import iso_to_ms, norm_path
from ccui.session.data.manager import SessionManager
from ccui.session.data.models import Session
from ccui.session.service.session_service import SessionService
from ccui.app.theme import (fmt_size, fmt_relative, trunc, COLOR_GROUP, COLOR_MUTED, COLOR_EMPTY, COLOR_LIVE)
from ccui.app.icons import provider_icon, role_icon_full, ui_icon
from ccui.app.widgets import EmptyHint, FadeMenu, PressButton
from ccui.session.view.dialogs import ResumeDialog, NewSessionDialog, DeleteDialog
from ccui.role.data import store as role_store
from ccui.role.data.manager import RoleManager


class SessionTree(QTreeWidget):
    """可感知 resize 的树：窗口缩放时通知面板重新应用列布局。"""
    viewResized = Signal()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.viewResized.emit()


MIN_SECTION = 40  # 列宽最小宽度（拖到这就拖不动）


class SessionPanel(QWidget):
    status_message = Signal(str, int)   # (text, timeout_ms) → 宿主窗口状态栏

    def __init__(self, parent=None):
        super().__init__(parent)
        self.service = SessionService()
        self.session_manager = SessionManager.instance()
        self.sessions = []
        self._by_id = {}
        self.selected = set()
        self._last_key = None
        self._suppress = False
        self._changed_at = 0  # 避免复选框点击双重切换
        self._entrance_done = False  # 首次入场淡入只做一次
        self._totals = {'count': 0, 'sizeBytes': 0, 'liveCount': 0}
        self._last_cwd = os.path.expanduser('~')
        self._user_widths = {}       # 用户手动拖过的列宽（自动布局时跳过）
        self._applying_layout = False
        self._build_ui()
        self._setup_watcher()
        self._rescan()
        if READONLY:
            self.status_message.emit('只读模式：删除已禁用', 0)
        log('会话面板启动')

    # ---- UI ----
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # 工具栏条带：底部细分割，层次分明
        toolbar_bar = QFrame()
        toolbar_bar.setObjectName('toolbarBar')
        toolbar = QHBoxLayout(toolbar_bar)
        toolbar.setContentsMargins(0, 0, 0, 10)
        self.btn_new = PressButton('新建会话')
        self.btn_new.setIcon(ui_icon('plus', 15, '#ffffff'))
        self.btn_new.setObjectName('btnNew')  # Apple 蓝主按钮
        self.btn_new.clicked.connect(self.on_new_session)
        toolbar.addWidget(self.btn_new)
        # 删除选中：纯图标（垃圾桶普世可辨识），危险红，tooltip 兜底
        self.btn_delete = QPushButton()
        self.btn_delete.setObjectName('iconBtn')
        self.btn_delete.setIcon(ui_icon('trash-2', 15, '#ff6961'))
        self.btn_delete.setIconSize(QSize(15, 15))
        self.btn_delete.setToolTip('删除选中')
        self.btn_delete.setProperty('danger', True)
        self.btn_delete.setFixedSize(34, 30)
        self.btn_delete.clicked.connect(self.on_delete)
        self.btn_delete.setEnabled(not READONLY)
        toolbar.addWidget(self.btn_delete)
        self.btn_empty = QPushButton('清理空会话')
        self.btn_empty.setIcon(ui_icon('broom', 15, '#c8c8cc'))
        self.btn_empty.setToolTip('一键删除所有空会话（有确认）')
        self.btn_empty.clicked.connect(self.on_clean_empty)
        toolbar.addWidget(self.btn_empty)
        # 导出/导入（zip）
        self.btn_export = QPushButton(' 导出')
        self.btn_export.setIcon(ui_icon('download', 14, '#c8c8cc'))
        self.btn_export.setToolTip('导出选中会话为 zip')
        self.btn_export.clicked.connect(self._export_selected)
        toolbar.addWidget(self.btn_export)
        self.btn_import = QPushButton(' 导入')
        self.btn_import.setIcon(ui_icon('upload', 14, '#c8c8cc'))
        self.btn_import.setToolTip('从 zip 导入会话')
        self.btn_import.clicked.connect(self._import_sessions)
        self.btn_import.setEnabled(not READONLY)
        toolbar.addWidget(self.btn_import)
        toolbar.addStretch(1)
        self.lbl_totals = QLabel('')
        self.lbl_totals.setObjectName('totals')
        toolbar.addWidget(self.lbl_totals)
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText('搜索标题 / 路径 / 模型…')
        self.edit_search.setMaximumWidth(240)
        self.edit_search.setClearButtonEnabled(True)
        self.edit_search.addAction(ui_icon('search', 14, '#6b6b70'),
                                   QLineEdit.ActionPosition.LeadingPosition)
        self.edit_search.textChanged.connect(self._schedule_rescan)  # 防抖：打字不逐键全量重建
        toolbar.addWidget(self.edit_search)
        root.addWidget(toolbar_bar)

        self.tree = SessionTree()
        self.tree.setHeaderLabels(['会话', '角色', '时间', '轮数', '模型', '大小', '状态'])
        self.tree.setRootIsDecorated(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = self.tree.header()
        header.setStretchLastSection(False)  # 空白留给标题列，不给最后一列
        header.setMinimumSectionSize(MIN_SECTION)  # 被拖的列不能小于最小宽
        # 列头图标：会话/角色/时间/轮数/模型/大小/状态（通过 model 的 DecorationRole）
        _model = self.tree.model()
        for icon, col in (('message-square', 0), ('users', 1), ('clock', 2),
                          ('repeat', 3), ('cpu', 4), ('database', 5), ('activity', 6)):
            _model.setHeaderData(col, Qt.Orientation.Horizontal,
                                 ui_icon(icon, 12, '#9a9aa0'), Qt.ItemDataRole.DecorationRole)
        # 全部 Interactive：用户可拖列宽；自动布局由 _apply_layout 管理
        for i in range(7):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)  # 双击恢复
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_session_menu)
        self.tree.setItemDelegate(LiveRowDelegate(self.tree))  # LIVE 行浅红底衬
        self.tree.viewResized.connect(self._apply_layout)
        header.sectionResized.connect(self._on_section_resized)
        root.addWidget(self.tree)
        # 空状态提示（随树缩放居中）
        self.empty_hint = EmptyHint('暂无会话\n点击「新建会话」开始', self.tree)
        self.tree.viewResized.connect(lambda: self.empty_hint.refresh())

    def _setup_watcher(self):
        self.watcher = QFileSystemWatcher(self)
        for p in (PROJECTS, SESSIONS_DIR, HISTORY, CLAUDE_JSON):
            if os.path.exists(p):
                self.watcher.addPath(p)
        self.watcher.directoryChanged.connect(self._schedule_rescan)
        self.watcher.fileChanged.connect(self._schedule_rescan)

        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(300)
        self.debounce.timeout.connect(self._rescan)

        self.tick = QTimer(self)
        self.tick.setInterval(2000)
        self.tick.timeout.connect(self._tick)
        self.tick.start()
        # LIVE 徽标微呼吸（运行中会话存在时才生效）
        self._breath = 0
        self.breath_timer = QTimer(self)
        self.breath_timer.setInterval(500)
        self.breath_timer.timeout.connect(self._breath_tick)
        self.breath_timer.start()
        # 事件驱动刷新：数据层变更（创建/删除/恢复/占位）→ 响应式重扫
        SignalHub.instance().subscribe('sessions.changed', self._schedule_rescan)

    def _schedule_rescan(self, *_):
        self.debounce.start()

    def _tick(self):
        if self.service.spawned or self._totals['liveCount'] > 0:
            self._rescan()

    def _breath_tick(self):
        """「● LIVE」呼吸：正弦明暗（亮红 #ff453a ↔ 暗红 #6e1a15，~4s 周期），清晰可见。"""
        if self._totals['liveCount'] <= 0:
            return
        self._breath += 1
        t = (math.sin(self._breath * 0.6) + 1) / 2.0   # 0..1 平滑往返
        r = int(255 - (255 - 110) * t)
        g = int(69 - (69 - 26) * t)
        b = int(58 - (58 - 21) * t)
        color = QColor(r, g, b)
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            for j in range(head.childCount()):
                row = head.child(j)
                sid = row.data(0, Qt.ItemDataRole.UserRole)
                s = self._by_id.get(sid) if sid else None
                if s and s.isLive:
                    row.setForeground(6, QBrush(color))
        self._render_totals(color)

    def _entrance_fade(self):
        """首次入场淡入（一次，结束后移除 effect 避免常驻栅格化）。"""
        if self._entrance_done:
            return
        self._entrance_done = True
        eff = QGraphicsOpacityEffect(self.tree)
        self.tree.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b'opacity')
        anim.setDuration(320)
        anim.setStartValue(0.25)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.tree.setGraphicsEffect(None))
        self._entrance_anim = anim
        anim.start()

    # ---- 扫描与渲染 ----
    def _rescan(self):
        try:
            sessions, totals = self.service.scan()
            self._totals = totals
        except Exception:
            log(f'scan 失败: {traceback.format_exc()}')
            return
        # 合并「角色启动中」会话：角色已追踪但无 transcript 且运行中（纯 live 驱动，
        # 进程退出即消失，与会话模块占位一致）。已被共享占位代表的跳过，避免重复。
        try:
            existing = {s.id for s in sessions}
            spawns = self.service.spawned
            for e in RoleManager.instance().starting_entries(existing, self.session_manager.live_ids()):
                if e['session_id'] in existing:
                    continue
                cwd = e.get('cwd') or ''
                ts_ms = iso_to_ms(e.get('timestamp', ''))
                if cwd and ts_ms and any(
                        sp.cwd and norm_path(sp.cwd) == norm_path(cwd)
                        and abs(sp.startedAt - ts_ms) <= 30000 for sp in spawns):
                    continue  # 已由共享占位（spawn-*）代表
                sessions.append(Session(
                    id=e['session_id'], project='role-starting',
                    projectPath=norm_path(cwd) or e['role'], title='',
                    firstTime='', lastTime='', userCount=0, assistantCount=0,
                    models=[], sizeBytes=0, isEmpty=True, isLive=True, isSpawned=True))
        except Exception:
            log(f'合并角色启动中会话失败: {traceback.format_exc()}')
        q = self.edit_search.text().strip().lower()
        if q:
            sessions = [s for s in sessions if self._matches(s, q)]
        key = tuple(
            (s.id, s.isLive, s.isSpawned, s.sizeBytes, s.lastTime,
             s.title, s.userCount, s.assistantCount, tuple(s.models))
            for s in sessions
        )
        if key == self._last_key:
            return
        self._last_key = key
        self.sessions = sessions
        self._by_id = {s.id: s for s in sessions}
        self.selected = {x for x in self.selected if x in self._by_id}
        self._rebuild_tree()

    def _matches(self, s, q):
        return (q in (s.title or '').lower() or q in (s.projectPath or '').lower()
                or q in s.id.lower() or any(q in m.lower() for m in s.models))

    def _on_section_resized(self, section, old_size, new_size):
        """用户拖动列边界：Qt 默认改的是左列，这里让右列吸收变化，
        使「右列右边缘」和它右侧所有列的绝对位置保持不动——
        拖动只影响边界相邻的两列（共享这条边界）。"""
        if self._applying_layout or new_size == old_size:
            return
        header = self.tree.header()
        target = section + 1
        if target < self.tree.columnCount():
            delta = old_size - new_size  # 左列变化量
            tgt_w = header.sectionSize(target) + delta  # 右列吸收
            self._applying_layout = True
            if tgt_w < MIN_SECTION:
                # 右列会被压到最小 → 左列继续吸收（保持两列总和不变），拖动被阻止
                left_new = old_size + (header.sectionSize(target) - MIN_SECTION)
                header.resizeSection(section, max(MIN_SECTION, left_new))
                header.resizeSection(target, MIN_SECTION)
            else:
                header.resizeSection(target, tgt_w)
            self._applying_layout = False
            self._user_widths[section] = header.sectionSize(section)
            self._user_widths[target] = header.sectionSize(target)
        else:
            self._user_widths[section] = new_size
        # 若右列被压到最小值导致总和 ≠ 视口，重新平衡保证右边缘贴合
        total = sum(header.sectionSize(i) for i in range(self.tree.columnCount()))
        if total != self.tree.viewport().width():
            self._rebalance()

    def _rebalance(self):
        """让列宽总和恰好等于视口宽，最后一列右边界始终贴窗。

        吸收器选择：默认标题列吸收（右侧列保持原位、拖哪个只动哪个）；
        若标题被用户拖过，则改用最后一列吸收（保证右边界仍贴合）。
        """
        header = self.tree.header()
        vp = self.tree.viewport().width()
        self._applying_layout = True
        try:
            if 0 not in self._user_widths:
                used = sum(header.sectionSize(i) for i in range(1, 7))
                header.resizeSection(0, max(80, vp - used))
            else:
                used = sum(header.sectionSize(i) for i in range(0, 6))
                header.resizeSection(6, max(40, vp - used))
        finally:
            self._applying_layout = False

    def _apply_layout(self):
        """自动列布局：内容列自适应、固定列恢复默认；吸收器由 _rebalance 决定
        （标题未拖过 → 标题吸收；拖过 → 最后一列吸收）。用户拖过的列跳过。"""
        self._applying_layout = True
        try:
            header = self.tree.header()
            for col in (3, 4):  # 轮数 / 模型：自适应内容
                if col not in self._user_widths:
                    self.tree.resizeColumnToContents(col)
            defaults = {1: 100, 2: 110, 5: 70, 6: 70}  # 角色100 时间110 大小70 状态70
            for col, w in defaults.items():
                if col not in self._user_widths:
                    header.resizeSection(col, w)
            if 0 not in self._user_widths:
                header.resizeSection(6, 70)  # 状态列默认宽（标题是吸收器时）
        finally:
            self._applying_layout = False
        self._rebalance()

    def _render_totals(self, live_color):
        """总数 stat 集群：会话数 / 体积 / 运行中（运行中用呼吸红点）。搜索时加匹配数。"""
        parts = []
        if self.edit_search.text().strip():
            parts.append(f'<b>{len(self.sessions)}</b> 个匹配')
        parts.append(f'<b>{self._totals["count"]}</b> 个会话')
        parts.append(fmt_size(self._totals['sizeBytes']))
        if self._totals['liveCount'] > 0:
            parts.append(f'<span style="color:{live_color.name()}; font-weight:600;">'
                         f'● {self._totals["liveCount"]} 运行中</span>')
        self.lbl_totals.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_totals.setText(' · '.join(parts))

    def _rebuild_tree(self):
        self._suppress = True
        self.tree.blockSignals(True)
        expanded = set()
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.isExpanded():
                expanded.add(it.text(0))
        self.tree.clear()
        self._role_map = role_store.session_role_map()
        self._provider_map = self.service.provider_map(self.sessions)
        groups = {}
        for s in self.sessions:
            groups.setdefault(s.projectPath, []).append(s)
        for proj in sorted(groups.keys(), key=lambda k: max((iso_to_ms(s.lastTime) for s in groups[k]), default=0), reverse=True):
            rows = groups[proj]
            head = QTreeWidgetItem()
            head.setFlags(head.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            head.setCheckState(0, self._group_state(rows))
            head.setText(0, proj)
            head.setToolTip(0, proj)  # 悬停显示完整路径
            # macOS 侧栏风格：正常字重、柔和灰，不比粗体黑
            _f = head.font(0); _f.setBold(False); _f.setPointSize(_f.pointSize() + 1); head.setFont(0, _f)
            head.setForeground(0, QBrush(QColor(COLOR_GROUP)))
            self.tree.addTopLevelItem(head)
            for s in rows:
                row = QTreeWidgetItem()
                row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                if s.isLive:
                    # 运行中：去掉勾选框但不禁用（禁用色会覆盖 setForeground 的呼吸色）
                    row.setFlags(row.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                else:
                    row.setCheckState(0, Qt.CheckState.Checked if s.id in self.selected else Qt.CheckState.Unchecked)
                row.setData(0, Qt.ItemDataRole.UserRole, s.id)
                if s.isSpawned:
                    spawned_txt = s.projectPath + ' · 运行中（等待首次输入）'
                    row.setText(0, trunc(spawned_txt, 110))
                    row.setToolTip(0, spawned_txt)
                    row.setForeground(0, QBrush(QColor(COLOR_EMPTY)))
                else:
                    full_title = s.title or '(空会话)'
                    row.setText(0, trunc(full_title, 120))
                    row.setToolTip(0, full_title)
                    if not s.title:
                        row.setForeground(0, QBrush(QColor(COLOR_EMPTY)))
                role = self._role_map.get(s.id, '')
                if role:
                    row.setText(1, role)
                    row.setToolTip(1, f'由角色 {role} 启动')
                    row.setIcon(1, role_icon_full(role, role_store.role_icon_path(role), 16))
                    row.setForeground(1, QBrush(QColor(COLOR_MUTED)))
                row.setText(2, fmt_relative(s.lastTime))
                if s.lastTime:
                    row.setToolTip(2, s.lastTime)
                turns_txt = '等待输入' if s.isSpawned else f"{s.userCount} 问 / {s.assistantCount} 答"
                row.setText(3, '等待输入' if s.isSpawned else f"{s.userCount}Q/{s.assistantCount}A")
                row.setToolTip(3, turns_txt)
                row.setText(4, trunc(' '.join(s.models), 40))
                if s.models:
                    row.setToolTip(4, ' '.join(s.models))
                prov = self._provider_map.get(s.id)
                if prov:
                    row.setIcon(4, provider_icon(prov))
                size_txt = '' if s.isSpawned else fmt_size(s.sizeBytes)
                row.setText(5, size_txt)
                if s.isSpawned:
                    pass
                elif size_txt:
                    row.setToolTip(5, f'{s.sizeBytes} 字节')
                if s.isLive:
                    row.setText(6, '● LIVE')
                    row.setToolTip(6, '正在运行')
                    row.setForeground(6, QBrush(QColor(COLOR_LIVE)))
                    row.setData(0, LIVE_ROLE, True)  # 浅红底衬（delegate 绘制）
                else:
                    row.setText(6, '已结束')
                    row.setForeground(6, QBrush(QColor(COLOR_MUTED)))
                head.addChild(row)
        if not expanded:
            self.tree.expandAll()
        else:
            for i in range(self.tree.topLevelItemCount()):
                self.tree.topLevelItem(i).setExpanded(self.tree.topLevelItem(i).text(0) in expanded)
        self.tree.blockSignals(False)
        self._suppress = False
        self._render_totals(QColor(COLOR_LIVE))
        self._apply_layout()
        # 空状态提示：搜索过滤无结果 vs 真无会话
        if self.tree.topLevelItemCount() == 0:
            if self.edit_search.text().strip():
                self.empty_hint.setText('无匹配的会话')
            else:
                self.empty_hint.setText('暂无会话\n点击「新建会话」开始')
            self.empty_hint.set_empty(True)
        else:
            self.empty_hint.set_empty(False)
        self._entrance_fade()

    def _group_state(self, rows):
        ids = [r.id for r in rows if not r.isLive]
        if not ids:
            return Qt.CheckState.Unchecked
        checked = sum(1 for i in ids if i in self.selected)
        if checked == 0:
            return Qt.CheckState.Unchecked
        if checked == len(ids):
            return Qt.CheckState.Checked
        return Qt.CheckState.PartiallyChecked

    def _update_group_check(self, head):
        checkable = []
        for i in range(head.childCount()):
            cid = head.child(i).data(0, Qt.ItemDataRole.UserRole)
            s = self._by_id.get(cid)
            if cid and s and not s.isLive:
                checkable.append(cid)
        if not checkable:
            state = Qt.CheckState.Unchecked
        else:
            checked = sum(1 for cid in checkable if cid in self.selected)
            state = (Qt.CheckState.Checked if checked == len(checkable)
                     else Qt.CheckState.Unchecked if checked == 0
                     else Qt.CheckState.PartiallyChecked)
        self._suppress = True
        head.setCheckState(0, state)
        self._suppress = False

    def _on_item_changed(self, item, column):
        if self._suppress or column != 0:
            return
        self._changed_at = time.time()
        sid = item.data(0, Qt.ItemDataRole.UserRole)
        if sid is None and item.parent() is None:
            checked = item.checkState(0) == Qt.CheckState.Checked
            for i in range(item.childCount()):
                child = item.child(i)
                cid = child.data(0, Qt.ItemDataRole.UserRole)
                s = self._by_id.get(cid)
                if not cid or not s or s.isLive:
                    continue
                self._suppress = True
                child.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                self._suppress = False
                if checked:
                    self.selected.add(cid)
                else:
                    self.selected.discard(cid)
            return
        if not sid or item.parent() is None:
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            self.selected.add(sid)
        else:
            self.selected.discard(sid)
        self._update_group_check(item.parent())

    def _on_item_clicked(self, item, column):
        if self._suppress:
            return
        sid = item.data(0, Qt.ItemDataRole.UserRole)
        if not sid:
            return
        s = self._by_id.get(sid)
        if s and s.isLive:
            return
        if time.time() - self._changed_at < 0.1:
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            item.setCheckState(0, Qt.CheckState.Unchecked)
        else:
            item.setCheckState(0, Qt.CheckState.Checked)

    # ---- 动作（委托给 service）----
    def on_new_session(self):
        provs = self.service.list_providers()
        dlg = NewSessionDialog(provs['names'], provs['default'], self._last_cwd, self,
                               sessions=self.sessions)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        cwd = dlg.directory()
        provider = dlg.provider()
        if not cwd:
            self.status_message.emit('未选择工作目录', 3000)
            return
        self._last_cwd = cwd
        inherit_ids = dlg.inherit_ids()
        inherit_path = self.service.build_inherit(inherit_ids) if inherit_ids else None
        spawned = self.service.new_session(cwd, provider, mode=dlg.mode(), inherit_path=inherit_path)
        if spawned is None:
            QMessageBox.warning(self, '启动失败', f'无法启动终端（目录：{cwd}）')
            return
        mode_txt = '危险模式' if dlg.mode() == 'danger' else '正常模式'
        suffix = f'，继承 {len(inherit_ids)} 个会话' if inherit_ids else ''
        self.status_message.emit(f'已在新终端启动会话（{cwd}，{provider}，{mode_txt}{suffix}）', 3000)
        self._rescan()
        QTimer.singleShot(2500, self._rescan)

    def on_delete(self):
        ids = [x for x in self.selected if x in self._by_id and not self._by_id[x].isLive]
        if not ids:
            self.status_message.emit('未选择任何可删除的会话', 3000)
            return
        items = [(self._by_id[x].title or '(空会话)', self._by_id[x].projectPath) for x in ids]
        total = sum(self._by_id[x].sizeBytes for x in ids)
        dlg = DeleteDialog(items, total, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        res = self.service.delete(ids)
        if res['deleted']:
            self.status_message.emit(
                f"已删除 {len(res['deleted'])} 个会话，释放 {fmt_size(res['totalFreed'])}"
                + (f"，{len(res['errors'])} 个失败" if res['errors'] else ''), 5000)
        else:
            self.status_message.emit('没有会话被删除', 3000)
        self.selected = set()
        self._rescan()

    def _on_item_double_clicked(self, item, column):
        """双击会话行 = 恢复（运行中由 on_resume 内部拦截）。"""
        sid = item.data(0, Qt.ItemDataRole.UserRole)
        if sid:
            self.on_resume(sid)

    def _show_session_menu(self, pos):
        """右键菜单：启动（恢复）/ 打开所在目录 / 复制 ID / 删除。运行中的会话前两项禁用。"""
        item = self.tree.itemAt(pos)
        if not item:
            return
        sid = item.data(0, Qt.ItemDataRole.UserRole)
        if not sid:
            return  # 分组标题行不弹菜单
        s = self._by_id.get(sid)
        menu = FadeMenu(self)
        act_start = menu.addAction(ui_icon('play', 15, '#d4d4d8'), '启动（恢复）')
        act_open = menu.addAction(ui_icon('folder-open', 15, '#d4d4d8'), '打开所在目录')
        act_copy = menu.addAction(ui_icon('copy', 15, '#d4d4d8'), '复制会话 ID')
        act_export = menu.addAction(ui_icon('download', 15, '#d4d4d8'), '导出')
        menu.addSeparator()
        act_del = menu.addAction(ui_icon('trash-2', 15, '#ff6961'), '删除')
        if s and s.isLive:
            act_start.setEnabled(False)
            act_del.setEnabled(False)
            act_export.setEnabled(False)
        if not (s and s.projectPath and os.path.isdir(s.projectPath)):
            act_open.setEnabled(False)
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen == act_start:
            self.on_resume(sid)
        elif chosen == act_open:
            self._open_project_dir(sid, s)
        elif chosen == act_copy:
            QApplication.clipboard().setText(sid)
            self.status_message.emit('会话 ID 已复制', 2000)
        elif chosen == act_export:
            self._export_session_ids([sid])
        elif chosen == act_del:
            self._delete_session(sid)

    def _open_project_dir(self, sid, s=None):
        if s is None:
            s = self._by_id.get(sid)
        proj = s.projectPath if s else ''
        if proj and os.path.isdir(proj):
            os.startfile(proj)
        else:
            self.status_message.emit('项目目录不存在', 3000)

    def _delete_session(self, sid):
        s = self._by_id.get(sid)
        title = (s.title if s else '') or '(空会话)'
        proj = (s.projectPath if s else '') or '未知项目'
        dlg = DeleteDialog([(title, proj)], s.sizeBytes if s else 0, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        res = self.service.delete([sid])
        if res['deleted']:
            self.status_message.emit('会话已删除', 3000)
        self._rescan()

    def on_clean_empty(self):
        """一键清理空会话：列出空会话（0 回复且非运行中）→ 确认 → 删除。"""
        empties = [s for s in self.sessions if s.isEmpty and not s.isLive]
        if not empties:
            self.status_message.emit('没有空会话', 3000)
            return
        ids = [s.id for s in empties]
        items = [(s.title or '(空会话)', s.projectPath) for s in empties]
        total = sum(s.sizeBytes for s in empties)
        dlg = DeleteDialog(items, total, self, title='清理空会话', confirm_text='确认清理',
                           intro=f'清理 {len(empties)} 个空会话？将释放约 {fmt_size(total)}：')
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        res = self.service.delete(ids)
        if res['deleted']:
            self.status_message.emit(
                f"已清理 {len(res['deleted'])} 个空会话，释放 {fmt_size(res['totalFreed'])}"
                + (f"，{len(res['errors'])} 个失败" if res['errors'] else ''), 5000)
        else:
            self.status_message.emit('没有空会话被删除', 3000)
        self.selected = set()
        self._rescan()

    def _export_session_ids(self, ids):
        if not ids:
            self.status_message.emit('未选择可导出的会话', 3000)
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出会话', 'sessions-export.zip',
                                              'Zip 档案 (*.zip)')
        if not path:
            return
        res = self.service.export_sessions(ids, path)
        if not res.get('ok'):
            QMessageBox.warning(self, '导出失败', res.get('error', '未知错误'))
            return
        self.status_message.emit(
            f"已导出 {len(res['exported'])} 个会话" + (f"，{len(res['skipped'])} 个跳过"
                                                     if res['skipped'] else ''), 4000)

    def _export_selected(self):
        ids = [x for x in self.selected if x in self._by_id and not self._by_id[x].isLive]
        self._export_session_ids(ids)

    def _import_sessions(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入会话', '', 'Zip 档案 (*.zip)')
        if not path:
            return
        res = self.service.import_session(path)
        if not res.get('ok'):
            QMessageBox.warning(self, '导入失败', res.get('error', '未知错误'))
            return
        msg = f"已导入 {len(res['imported'])} 个会话"
        if res.get('conflicts'):
            msg += f"；{len(res['conflicts'])} 个已存在跳过"
        self.status_message.emit(msg, 5000)
        self._rescan()

    def on_resume(self, sid):
        s = self._by_id.get(sid)
        if not s or s.isLive:
            return
        provs = self.service.list_providers()
        default_provider = self.service.resolve_provider(sid, s.models)
        default_mode = self.service.detect_permission_mode(sid)
        dlg = ResumeDialog(default_mode, trunc(s.title or sid[:8], 40),
                           provs['names'], default_provider, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        mode = dlg.mode()
        provider = dlg.provider()
        if self.service.resume(sid, mode, provider):
            self.status_message.emit(f'已在新终端恢复会话（{mode}模式，{provider}）', 3000)
        else:
            QMessageBox.warning(self, '启动失败', f'无法启动终端恢复会话（{sid}）')
