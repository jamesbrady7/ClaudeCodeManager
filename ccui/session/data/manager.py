"""SessionManager：会话注册表（会话模块 data 层，进程内单例）。

同源真相：所有会话（含 UI 启动中的占位）都以 uuid 登记在此。
会话模块自身与角色模块的 View 都通过它查询会话的存在与 state，
不再各自扫描 transcript，避免数据劈叉。

隔离：只依赖本模块 data（store）；不 import 其他业务模块。
"""
from ccui.session.data import store
from ccui.infra.signalhub import SignalHub


class SessionManager:
    _instance = None

    def __init__(self):
        # UI 启动、等待首次输入的占位（SpawnedSession）；由 scan 合并进列表
        self.spawned = []

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_spawn(self, spawned):
        """登记一个 UI 启动的占位会话，并广播 sessions.changed（各视图响应刷新）。"""
        self.spawned.append(spawned)
        SignalHub.instance().emit('sessions.changed')

    def scan(self):
        """全部会话列表 + 总量统计（真实 transcript + 占位合并）。

        scan_sessions 会就地清理已物化的占位（spawned 同步）。
        """
        return store.scan_sessions(self.spawned)

    def by_id(self):
        """uuid -> Session 映射（真实 + 占位）。"""
        sessions, _ = self.scan()
        return {s.id: s for s in sessions}

    def live_ids(self):
        """运行中会话的 uuid 集合（sessions/*.json + psutil 存活）。"""
        return set(store.live_session_map())
