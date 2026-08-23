"""角色面板（view 层）：左侧角色列表 + 右侧该角色的会话/详情（主从布局）。

编排层：View 允许跨模块调用 Data/Service。会话列表渲染 =
  RoleManager（拿该角色追踪的 uuid 列表）→ SessionManager（按 uuid 查存在与 state）。
"""
import os
import time
import traceback

from PySide6.QtCore import Qt, QTimer, QFileSystemWatcher, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QPushButton, QLabel, QDialog, QMenu,
    QAbstractItemView, QHeaderView, QMessageBox,
)

from ccui.infra.config import ROLES_DIR, SKILLS_DIR, PROJECTS, SESSIONS_DIR, log
from ccui.infra.signalhub import SignalHub
from ccui.infra.utils import iso_to_ms
from ccui.app.theme import fmt_time, trunc
from ccui.session.data.manager import SessionManager
from ccui.session.data.models import Session, SpawnedSession
from ccui.role.data.manager import RoleManager
from ccui.role.service.role_service import RoleService
from ccui.session.service.session_service import SessionService
from ccui.session.view.dialogs import ResumeDialog, DeleteDialog, InheritDialog
from ccui.role.view.dialogs import (
    NewRoleDialog, SkillsDialog, KnowledgeDialog,
)


def _placeholder_session(uuid):
    """启动中占位 Session（无 transcript、运行中/等待物化）。"""
    return Session(id=uuid, project='', projectPath='', title='',
                   firstTime='', lastTime='', userCount=0, assistantCount=0,
                   models=[], sizeBytes=0, isEmpty=True,
                   isLive=True, isSpawned=True)


class RolePanel(QWidget):
    status_message = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.service = RoleService()
        self.session_service = SessionService()
        self.session_manager = SessionManager.instance()
        self.role_manager = RoleManager.instance()
        self.roles = []
        self.current_role = None
        self._role_live = False   # 当前角色是否有会话运行中（驱动 live tick）
        self._pending = {}        # name -> [(伪uuid, ts_ms)]：spawn 后、hook 写入前的占位
        self._build_ui()
        self._setup_watcher()
        self._load_roles()

    # ---- UI ----
    def _build_ui(self):
        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左：角色列表
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(8, 8, 4, 8)
        self.btn_new_role = QPushButton('+ 新建角色')
        self.btn_new_role.clicked.connect(self._new_role)
        left_lay.addWidget(self.btn_new_role)
        self.role_list = QListWidget()
        self.role_list.setMinimumWidth(180)
        self.role_list.currentItemChanged.connect(self._on_role_selected)
        left_lay.addWidget(self.role_list)

        # 右：角色详情 + 会话
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(4, 8, 8, 8)
        self.lbl_name = QLabel('选择左侧角色')
        _f = self.lbl_name.font(); _f.setPointSize(_f.pointSize() + 4); _f.setBold(True)
        self.lbl_name.setFont(_f)
        right_lay.addWidget(self.lbl_name)
        self.lbl_desc = QLabel('')
        self.lbl_desc.setWordWrap(True)
        right_lay.addWidget(self.lbl_desc)

        skill_row = QHBoxLayout()
        self.lbl_skills = QLabel('')
        skill_row.addWidget(self.lbl_skills, 1)
        self.btn_skills = QPushButton('管理技能')
        self.btn_skills.clicked.connect(self._manage_skills)
        skill_row.addWidget(self.btn_skills)
        right_lay.addLayout(skill_row)

        action_row = QHBoxLayout()
        self.btn_start = QPushButton('创建角色会话')
        self.btn_start.clicked.connect(self._start)
        self.btn_knowledge = QPushButton('编辑知识库')
        self.btn_knowledge.clicked.connect(self._edit_knowledge)
        action_row.addWidget(self.btn_start)
        action_row.addWidget(self.btn_knowledge)
        action_row.addStretch(1)
        right_lay.addLayout(action_row)

        self.session_tree = QTreeWidget()
        self.session_tree.setColumnCount(4)
        self.session_tree.setHeaderLabels(['标题', '时间', '轮数', '模型'])
        self.session_tree.setRootIsDecorated(False)
        self.session_tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        # 无选择模式：失焦时被选中行会用 Inactive 配色导致文字变黑（主面板同款规避）
        self.session_tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        # 操作改右键菜单（启动/恢复、删除）
        self.session_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_tree.customContextMenuRequested.connect(self._show_session_menu)
        header = self.session_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.session_tree.setColumnWidth(1, 90)
        self.session_tree.setColumnWidth(2, 70)
        right_lay.addWidget(self.session_tree)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        root.addWidget(splitter)

    def _setup_watcher(self):
        self.watcher = QFileSystemWatcher(self)
        # PROJECTS：角色会话的 transcript 在 projects/ 下生成时触发刷新（占位 → 真实标题）
        # SESSIONS_DIR：sessions/*.json 增删 → liveness 变化触发刷新
        for p in (ROLES_DIR, SKILLS_DIR, PROJECTS, SESSIONS_DIR):
            if os.path.exists(p):
                self.watcher.addPath(p)
        self.watcher.directoryChanged.connect(self._schedule_reload)
        self.watcher.fileChanged.connect(self._schedule_reload)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(400)
        self.debounce.timeout.connect(self._reload_all)
        # 会话运行态轮询（会话模块同款思路）：有角色会话运行中时每 3s 刷新，
        # 捕获「进程结束」这类文件系统事件捕获不到的 liveness 变化
        self.live_tick = QTimer(self)
        self.live_tick.setInterval(3000)
        self.live_tick.timeout.connect(self._tick_live)
        self.live_tick.start()
        # 事件驱动刷新：数据层变更 → 响应式重载（会话/角色/角色会话三类事件）
        hub = SignalHub.instance()
        hub.subscribe('sessions.changed', self._schedule_reload)
        hub.subscribe('roles.changed', self._schedule_reload)
        hub.subscribe('role.sessions.changed', self._on_role_sessions_changed)

    def _on_role_sessions_changed(self, name=''):
        if name and self.current_role and name != self.current_role.name:
            return  # 无关角色的会话变化不刷新
        self._schedule_reload()

    def _watch_role_session_files(self):
        """监听各角色 sessions.jsonl：hook 启动角色会话时是向文件追加内容，
        只触发对该文件的 fileChanged，目录的 directoryChanged 不覆盖。"""
        for r in self.roles:
            p = os.path.join(ROLES_DIR, r.name, 'sessions.jsonl')
            if os.path.isfile(p):
                self.watcher.addPath(p)

    def _schedule_reload(self, *_):
        self.debounce.start()

    def _reload_all(self):
        name = self.current_role.name if self.current_role else None
        self._load_roles()
        if name:
            role = next((r for r in self.roles if r.name == name), None)
            if role:
                self.current_role = role  # 用最新 Role 对象，避免陈旧引用
                # 显式刷新会话列表：_load_roles 在 blockSignals 中已重设当前项，
                # selection 信号不会触发 _show_role，需直接调用（key 守卫决定是否重建）
                self._load_role_sessions(name)

    # ---- 角色列表 ----
    def _load_roles(self):
        try:
            self.roles = self.service.list_roles()
        except Exception:
            log(f'加载角色失败: {traceback.format_exc()}')
            return
        self._watch_role_session_files()
        current = None
        if self.role_list.currentItem():
            current = self.role_list.currentItem().data(Qt.ItemDataRole.UserRole)
        self.role_list.blockSignals(True)
        self.role_list.clear()
        for r in self.roles:
            item = QListWidgetItem(f"{r.name}（{r.sessionCount}）")
            item.setData(Qt.ItemDataRole.UserRole, r.name)
            item.setToolTip(r.description)
            self.role_list.addItem(item)
            if r.name == current:
                self.role_list.setCurrentItem(item)
        self.role_list.blockSignals(False)
        if not current and self.roles:
            self.role_list.setCurrentRow(0)
        if not self.roles:
            self._clear_detail()

    def _on_role_selected(self, current, previous):
        if not current:
            self._clear_detail()
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        role = next((r for r in self.roles if r.name == name), None)
        if role:
            self._show_role(role)

    def _clear_detail(self):
        self.current_role = None
        self.lbl_name.setText('选择左侧角色')
        self.lbl_desc.setText('')
        self.lbl_skills.setText('')
        self.session_tree.clear()

    def _show_role(self, role):
        self.current_role = role
        self.lbl_name.setText(role.name)
        self.lbl_desc.setText(role.description or '')
        self.lbl_skills.setText('技能：' + ('、'.join(role.skills) if role.skills else '（无）'))
        self._load_role_sessions(role.name, force=True)

    # ---- 角色会话 ----
    def _load_role_sessions(self, name, force=False):
        """渲染角色会话列表：RoleManager 拿 uuid 列表 → SessionManager 查存在与 state。

        判定规则（同源）：
          · transcript 存在        → 真实会话（标题/时间/轮数/模型/isLive 用 Session 的）
          · 无 transcript 但运行中  → 启动中占位（禁用）
          · 无 transcript 且非 live → 孤儿（不显示，超龄由 RoleManager.prune_stale 清文件）
        另加视图级 pending 占位（点击创建后、hook 写入前的即时反馈）。
        """
        try:
            sm = self.session_manager
            existing = sm.by_id()
            live = sm.live_ids()
            self.role_manager.prune_stale(name, set(existing) | live)
            tracked = self.role_manager.session_entries(name)
        except Exception:
            log(f'加载角色会话失败: {traceback.format_exc()}')
            return
        now = int(time.time() * 1000)
        spawn_alive = {sp.startedAt for sp in self.session_manager.spawned}  # 共享占位=进程存活
        rows = []   # [(uuid, Session)]：真实 + 启动中占位
        for t in tracked:
            sid = t.get('session_id', '')
            if not sid:
                continue
            s = existing.get(sid)
            if s:
                rows.append((sid, s))
            elif sid in live:
                # 运行中但无 transcript → 启动中（纯 live 驱动，进程退出即消失）
                rows.append((sid, _placeholder_session(sid)))
            # else: 无 transcript 且不运行 → 已关闭/孤儿，跳过
        # 视图级 pending：真实会话 live、或共享占位进程退出、或超龄(>20s)则清除
        pending = self._pending.get(name, [])
        kept_pending = []
        for puuid, pts in pending:
            materialized = any(
                t.get('session_id') in live and iso_to_ms(t.get('timestamp', '')) >= pts
                for t in tracked
            )
            if materialized or pts not in spawn_alive or (now - pts) > 20000:
                continue
            kept_pending.append((puuid, pts))
            rows.append((puuid, _placeholder_session(puuid)))
        self._pending[name] = kept_pending
        # key 守卫：无关事件不重建树；isLive/isSpawned 纳入以同步运行态
        key = tuple(
            (u, s.isLive, s.isSpawned, s.title, s.lastTime,
             s.userCount, s.assistantCount, tuple(s.models))
            for u, s in rows
        )
        if not force and key == getattr(self, '_role_sess_key', None):
            return
        self._role_sess_key = key
        self._role_live = any(s.isLive for _, s in rows)
        self.session_tree.clear()
        for u, s in rows:
            item = QTreeWidgetItem()
            if s.isSpawned:
                title, tooltip = '(启动中…)', '正在启动'
            else:
                title = s.title or ('(空会话) ' + u[:8])
                tooltip = s.title or u
            if s.isLive and not s.isSpawned:
                title += '（运行中）'
            item.setText(0, trunc(title, 70))
            item.setToolTip(0, tooltip + (' · 正在运行' if s.isLive else ''))
            if not s.isSpawned:
                item.setText(1, fmt_time(s.lastTime))
                item.setText(2, f"{s.userCount}Q/{s.assistantCount}A")
                item.setText(3, trunc(' '.join(s.models), 40))
            item.setData(0, Qt.ItemDataRole.UserRole, u)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, s)  # 右键菜单取 isLive
            if s.isLive:
                item.setDisabled(True)
            self.session_tree.addTopLevelItem(item)

    def _show_session_menu(self, pos):
        """右键菜单：启动（恢复）/ 删除；运行中的会话两项都禁用。"""
        item = self.session_tree.itemAt(pos)
        if not item:
            return
        sid = item.data(0, Qt.ItemDataRole.UserRole)
        sess = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not sid or not sess:
            return
        menu = QMenu(self)
        act_start = menu.addAction('启动（恢复）')
        act_del = menu.addAction('删除')
        if sess.isLive:
            act_start.setEnabled(False)
            act_del.setEnabled(False)
        chosen = menu.exec(self.session_tree.viewport().mapToGlobal(pos))
        if chosen == act_start:
            self._resume_session(sid, sess)
        elif chosen == act_del:
            self._delete_session(sid, sess)

    def _tick_live(self):
        # 有角色会话运行中时每 3s 刷新，捕获「进程结束」这类事件捕获不到的 liveness 变化
        if self._role_live and self.current_role:
            self._load_role_sessions(self.current_role.name)

    def _resume_session(self, sid, ref=None):
        # 优先用右键菜单已持有的 Session，避免全量扫描 transcript
        if ref is None:
            ref = self.session_manager.by_id().get(sid)
        provs = self.session_service.list_providers()
        default_provider = self.session_service.resolve_provider(sid, ref.models if ref else [])
        default_mode = self.session_service.detect_permission_mode(sid)
        dlg = ResumeDialog(default_mode, trunc((ref.title if ref else '') or sid[:8], 40),
                           provs['names'], default_provider, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if self.session_service.resume(sid, dlg.mode(), dlg.provider()):
            self.status_message.emit(f'已在新终端恢复会话（{dlg.mode()}模式）', 3000)
            self._schedule_refresh_burst()

    def _delete_session(self, sid, ref=None):
        # 优先用右键菜单已持有的 Session，避免全量扫描 transcript（大文件会卡弹窗）
        if ref is None:
            ref = self.session_manager.by_id().get(sid)
        title = (ref.title if ref else '') or '(空会话)'
        proj = (ref.projectPath if ref else '') or self.current_role.name
        dlg = DeleteDialog([(title, proj)], ref.sizeBytes if ref else 0, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        res = self.session_service.delete([sid])  # 成功后 emit sessions.changed → 各视图响应刷新
        if res['deleted']:
            self.role_manager.remove_session(self.current_role.name, sid)  # 清该角色记录
            self.status_message.emit('已删除角色会话', 3000)
        else:
            self.status_message.emit('删除失败（可能仍在运行）', 3000)

    def _refresh_current(self):
        """刷新当前角色的会话列表（key 守卫，无变化不重建）。"""
        if self.current_role:
            self._load_role_sessions(self.current_role.name)

    def _schedule_refresh_burst(self):
        """spawn 后补偿刷新：claude 要几秒才启动、hook 才写 sessions.jsonl，
        分段刷几次覆盖该延迟；watcher 继续作为被动兜底。"""
        for delay in (1000, 2000, 4000, 8000):
            QTimer.singleShot(delay, self._refresh_current)

    # ---- 动作 ----
    def _new_role(self):
        skills = self.service.list_skills()
        dlg = NewRoleDialog(skills, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, desc, selected = dlg.name(), dlg.description(), dlg.selected_skills()
        if not name:
            self.status_message.emit('请输入角色名称', 3000)
            return
        r = self.service.create_role(name, desc, selected)
        if r['ok']:
            self.status_message.emit(f'角色 {name} 已创建', 3000)
            self._load_roles()
            for i in range(self.role_list.count()):
                if self.role_list.item(i).data(Qt.ItemDataRole.UserRole) == name:
                    self.role_list.setCurrentRow(i)
                    break
        else:
            self.status_message.emit('创建失败：' + (r.get('error') or ''), 3000)

    def _start(self):
        if not self.current_role:
            return
        sessions, _ = self.session_service.scan()
        dlg = InheritDialog(sessions, self, title='创建角色会话',
                            ok_text='创建', hint='不勾选任何会话则直接创建新会话')
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        ids = dlg.selected_ids()
        name = self.current_role.name
        proc = self.service.start_role(name, ids)
        if proc:
            started_at = int(time.time() * 1000)
            # 登记共享占位 → 广播 sessions.changed，会话面板立即显示（两侧同步）
            try:
                spawned = SpawnedSession(cwd=os.path.dirname(ROLES_DIR), startedAt=started_at,
                                         pid=proc.pid if hasattr(proc, 'pid') else proc,
                                         proc=proc, provider='')
                self.session_manager.register_spawn(spawned)
            except Exception:
                log(f'登记角色启动占位失败: {traceback.format_exc()}')
            # 角色视图自己的「启动中」占位（hook 写入前）
            self._pending.setdefault(name, []).append((f'role-spawn-{name}-{started_at}', started_at))
            self.status_message.emit(
                f'已在新终端创建角色会话：{name}'
                + (f'（继承 {len(ids)} 个会话）' if ids else ''), 3000)
            self._refresh_current()
            self._schedule_refresh_burst()
        else:
            self.status_message.emit('启动失败', 3000)

    def _edit_knowledge(self):
        if not self.current_role:
            return
        content = self.service.get_knowledge(self.current_role.name)
        dlg = KnowledgeDialog(self.current_role.name, content, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.service.write_knowledge(self.current_role.name, dlg.content())
            self.status_message.emit('知识库已保存', 3000)

    def _manage_skills(self):
        if not self.current_role:
            return
        all_skills = self.service.list_skills(self.current_role.name)
        dlg = SkillsDialog(self.current_role.name, all_skills, self.current_role.skills, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.service.update_skills(self.current_role.name, dlg.selected_skills())
        self.status_message.emit('技能已更新', 3000)
        self._load_roles()
