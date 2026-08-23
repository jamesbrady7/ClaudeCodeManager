"""SignalHub：基础设施层事件总线（进程内单例，纯 Python，无 Qt）。

「谁改数据谁通知」：数据/Service 层修改内容后 emit 事件；View 层 subscribe
事件做响应式刷新。这样展示层刷新依赖数据层，各视图（会话模块 / 角色模块）
订阅同一事件，状态天然一致，不再由 View 直接操作列表。

事件约定：
  sessions.changed       会话数据/状态变化（创建/删除/恢复/占位登记）
  roles.changed          角色列表变化（增删角色）
  role.sessions.changed  某角色追踪的会话记录变化（payload: name）
"""
from ccui.infra.config import log


class SignalHub:
    _instance = None

    def __init__(self):
        self._subs = {}   # event -> list[callable]

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def emit(self, event, **payload):
        """发事件：同步调用已订阅的处理器；单个处理器异常不影响其他。"""
        for fn in list(self._subs.get(event, ())):
            try:
                fn(**payload)
            except Exception as e:
                log(f'signalhub 事件 {event} 处理器异常: {e}')

    def subscribe(self, event, fn):
        self._subs.setdefault(event, []).append(fn)

    def unsubscribe(self, event, fn):
        subs = self._subs.get(event)
        if subs and fn in subs:
            subs.remove(fn)
