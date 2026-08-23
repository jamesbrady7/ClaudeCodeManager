"""会话模块独立面板（view 层）：会话列表 UI + 事件 → 调 SessionService。

通过 status_message 信号把状态消息发给宿主窗口（MainWindow 的 statusBar）。
"""
import os
import time
import traceback

from PySide6.QtCore import Qt, QTimer, QFileSystemWatcher, Signal
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QLineEdit, QDialog, QFileDialog, QMessageBox,
    QAbstractItemView, QHeaderView,
)

from ccui.infra.config import PROJECTS, SESSIONS_DIR, HISTORY, CLAUDE_JSON, READONLY, log
from ccui.infra.signalhub import SignalHub
from ccui.infra.utils import iso_to_ms, norm_path
from ccui.session.data import store
from ccui.session.data.manager import SessionManager
from ccui.session.data.models import Session
from ccui.session.service.session_service import SessionService
from ccui.app.theme import fmt_size, fmt_time, trunc, COLOR_GROUP, COLOR_MUTED, COLOR_EMPTY, COLOR_LIVE
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

        toolbar = QHBoxLayout()
        self.btn_new = QPushButton('新建会话')
        self.btn_new.setObjectName('btnNew')  # Apple 蓝主按钮
        self.btn_new.clicked.connect(self.on_new_session)
        toolbar.addWidget(self.btn_new)
        self.btn_delete = QPushButton('删除选中')
        self.btn_delete.setProperty('danger', True)
        self.btn_delete.clicked.connect(self.on_delete)
        self.btn_delete.setEnabled(not READONLY)
        toolbar.addWidget(self.btn_delete)
        self.btn_empty = QPushButton('选中空会话')
        self.btn_empty.clicked.connect(self.on_select_empty)
        toolbar.addWidget(self.btn_empty)
        self.btn_refresh = QPushButton('刷新')
        self.btn_refresh.clicked.connect(self._rescan)
        toolbar.addWidget(self.btn_refresh)
        toolbar.addStretch(1)
        self.lbl_totals = QLabel('')
        self.lbl_totals.setObjectName('totals')
        toolbar.addWidget(self.lbl_totals)
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText('搜索标题 / 路径 / 模型…')
        self.edit_search.setMaximumWidth(240)
        self.edit_search.textChanged.connect(self._rescan)
        toolbar.addWidget(self.edit_search)
        root.addLayout(toolbar)

        self.tree = SessionTree()
        self.tree.setColumnCount(8)
        self.tree.setHeaderLabels(['会话', '角色', '时间', '轮数', '模型', '大小', '状态', '操作'])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = self.tree.header()
        header.setStretchLastSection(False)  # 空白留给标题列，不给最后一列
        header.setMinimumSectionSize(MIN_SECTION)  # 被拖的列不能小于最小宽
        # 全部 Interactive：用户可拖列宽；自动布局由 _apply_layout 管理
        for i in range(8):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.viewResized.connect(self._apply_layout)
        header.sectionResized.connect(self._on_section_resized)
        root.addWidget(self.tree)

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
        # 事件驱动刷新：数据层变更（创建/删除/恢复/占位）→ 响应式重扫
        SignalHub.instance().subscribe('sessions.changed', self._schedule_rescan)

    def _schedule_rescan(self, *_):
        self.debounce.start()

    def _tick(self):
        if self.service.spawned or self._totals['liveCount'] > 0:
            self._rescan()

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
                used = sum(header.sectionSize(i) for i in range(1, 8))
                header.resizeSection(0, max(80, vp - used))
            else:
                used = sum(header.sectionSize(i) for i in range(0, 7))
                header.resizeSection(7, max(40, vp - used))
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
            defaults = {1: 90, 2: 90, 5: 60, 6: 60}  # 角色/时间 90，大小/状态 60
            for col, w in defaults.items():
                if col not in self._user_widths:
                    header.resizeSection(col, w)
            if 0 not in self._user_widths:
                header.resizeSection(7, 60)  # 操作列默认宽（标题是吸收器时）
        finally:
            self._applying_layout = False
        self._rebalance()

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
                    row.setCheckState(0, Qt.CheckState.Unchecked)
                    row.setDisabled(True)
                else:
                    row.setCheckState(0, Qt.CheckState.Checked if s.id in self.selected else Qt.CheckState.Unchecked)
                row.setData(0, Qt.ItemDataRole.UserRole, s.id)
                if s.isSpawned:
                    spawned_txt = s.projectPath + ' · 运行中（等待首次输入）'
                    row.setText(0, trunc(spawned_txt, 70))
                    row.setToolTip(0, spawned_txt)
                    row.setForeground(0, QBrush(QColor(COLOR_EMPTY)))
                else:
                    full_title = s.title or '(空会话)'
                    row.setText(0, trunc(full_title, 80))
                    row.setToolTip(0, full_title)
                    if not s.title:
                        row.setForeground(0, QBrush(QColor(COLOR_EMPTY)))
                role = self._role_map.get(s.id, '')
                if role:
                    row.setText(1, role)
                    row.setToolTip(1, f'由角色 {role} 启动')
                    row.setForeground(1, QBrush(QColor(COLOR_MUTED)))
                row.setText(2, fmt_time(s.lastTime))
                if s.lastTime:
                    row.setToolTip(2, s.lastTime)
                turns_txt = '等待输入' if s.isSpawned else f"{s.userCount} 问 / {s.assistantCount} 答"
                row.setText(3, '等待输入' if s.isSpawned else f"{s.userCount}Q/{s.assistantCount}A")
                row.setToolTip(3, turns_txt)
                row.setText(4, trunc(' '.join(s.models), 40))
                if s.models:
                    row.setToolTip(4, ' '.join(s.models))
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
                else:
                    row.setText(6, '')
                head.addChild(row)
                if not s.isLive:
                    btn = QPushButton('恢复')
                    btn.setObjectName('btnResume')
                    btn.setFixedWidth(48)
                    btn.clicked.connect(lambda _=False, sid=s.id: self.on_resume(sid))
                    self.tree.setItemWidget(row, 7, btn)
        if not expanded:
            self.tree.expandAll()
        else:
            for i in range(self.tree.topLevelItemCount()):
                self.tree.topLevelItem(i).setExpanded(self.tree.topLevelItem(i).text(0) in expanded)
        self.tree.blockSignals(False)
        self._suppress = False
        self.lbl_totals.setText(
            f"{self._totals['count']} 个会话 · {fmt_size(self._totals['sizeBytes'])} · "
            f"{self._totals['liveCount']} 个运行中")
        self._apply_layout()

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
        if self._suppress or column == 7:
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
        spawned = self.service.new_session(cwd, provider, inherit_path=inherit_path)
        if spawned is None:
            QMessageBox.warning(self, '启动失败', f'无法启动终端（目录：{cwd}）')
            return
        suffix = f'，继承 {len(inherit_ids)} 个会话' if inherit_ids else ''
        self.status_message.emit(f'已在新终端启动会话（{cwd}，{provider}{suffix}）', 3000)
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

    def on_select_empty(self):
        self.selected = self.service.select_empty(self.sessions)
        self.status_message.emit(f'已选中 {len(self.selected)} 个空会话', 3000)
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
