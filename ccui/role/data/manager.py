"""RoleManager：角色注册表（角色模块 data 层，进程内单例）。

map：name -> Role；每个 Role 持有该角色追踪的会话 uuid 列表（来自 sessions.jsonl）。
会话存在/运行态等判断所需信息由 View 以参数传入（如 existing_ids），
本模块**不 import 任何 session 模块**，保证各模块 Data/Service 层隔离。
"""
import uuid as uuidlib
import datetime

from ccui.infra.signalhub import SignalHub
from ccui.role.data import store as role_store
from ccui.role.data.models import Role


class RoleManager:
    _instance = None

    def __init__(self):
        self._roles = {}   # name -> Role（map 管理所有角色）

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self):
        """从磁盘重建角色 map（meta.json + sessions.jsonl + knowledge），并回填缺失 uuid。"""
        roles = {}
        for name in role_store.list_role_names():
            meta = role_store.read_meta(name)
            tracked = role_store.role_sessions_from_file(name)
            k = role_store.read_knowledge(name)
            roles[name] = Role(
                name=name,
                uuid=meta.get('uuid', ''),
                description=meta.get('description', ''),
                skills=meta.get('skills', []),
                created=meta.get('created', ''),
                session_ids=[t['session_id'] for t in tracked if t.get('session_id')],
                sessionCount=len(tracked),
                knowledgeSize=len(k.encode('utf-8')),
                knowledgeExists=bool(k),
            )
        # 兼容 cc-role.ps1 新建的旧角色：缺失 uuid 时生成并写回 meta.json
        for name, role in roles.items():
            if not role.uuid:
                role.uuid = str(uuidlib.uuid4())
                meta = role_store.read_meta(name)
                meta['uuid'] = role.uuid
                role_store.write_meta(name, meta)
        self._roles = roles
        return roles

    def roles(self):
        """全部角色（最新，从磁盘读取）。"""
        return list(self._load().values())

    def get(self, name):
        return self._load().get(name)

    def session_entries(self, name):
        """该角色追踪的会话原始条目 [{session_id, timestamp, cwd}]。"""
        return role_store.role_sessions_from_file(name)

    def starting_entries(self, existing_ids, live_ids):
        """跨角色汇总「启动中」会话：已追踪但无 transcript 且**运行中**。

        纯 live 驱动（与会话模块同源）：进程退出即不显示，避免关闭后残留。
        existing_ids / live_ids 由调用方（View）从 SessionManager 取得，本模块不碰 session 层。
        """
        out = []
        for name in role_store.list_role_names():
            for t in role_store.role_sessions_from_file(name):
                sid = t.get('session_id', '')
                if sid and sid not in existing_ids and sid in live_ids:
                    out.append({'role': name, 'session_id': sid, 'timestamp': t.get('timestamp', ''),
                                'cwd': t.get('cwd', '')})
        return out

    def prune_stale(self, name, existing_ids, min_age_seconds=600):
        """清掉不在 existing_ids 里且记录足够旧的孤儿（年龄守卫防误删刚启动的）。

        existing_ids 由 View 传入（真实 transcript 的 uuid ∪ 运行中 uuid）。
        """
        tracked = role_store.role_sessions_from_file(name)
        now = datetime.datetime.now(datetime.timezone.utc)
        kept = []
        removed = []
        for t in tracked:
            sid = t.get('session_id', '')
            if sid in existing_ids:
                kept.append(t)
                continue
            ts = t.get('timestamp', '')
            try:
                dt = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
                stale = (now - dt).total_seconds() >= min_age_seconds
            except Exception:
                stale = True  # 无法解析时间的记录一并清掉
            if stale:
                removed.append(sid)
            else:
                kept.append(t)
        if removed:
            role_store.write_role_sessions(name, kept)
            SignalHub.instance().emit('role.sessions.changed', name=name)
        return {'ok': True, 'removed': removed}

    def remove_session(self, name, session_id):
        """从该角色的 sessions.jsonl 移除指定 session_id。"""
        tracked = role_store.role_sessions_from_file(name)
        kept = [t for t in tracked if t.get('session_id', '') != session_id]
        if len(kept) != len(tracked):
            role_store.write_role_sessions(name, kept)
            SignalHub.instance().emit('role.sessions.changed', name=name)
        return {'ok': True}
