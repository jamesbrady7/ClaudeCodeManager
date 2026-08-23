"""会话数据模型（会话模块 data 层）。"""
from dataclasses import dataclass


@dataclass
class Session:
    """一个会话的摘要数据：时间 / 轮数 / 模型 / 大小等。"""
    id: str
    project: str
    projectPath: str
    title: str
    firstTime: str
    lastTime: str
    userCount: int
    assistantCount: int
    models: list
    sizeBytes: int
    isEmpty: bool
    isLive: bool = False    # 由进程存活接口在扫描时填充，不重复存储
    isSpawned: bool = False  # 本应用启动、等待首次输入的占位


@dataclass
class SpawnedSession:
    """本应用启动的、等待首次输入的会话（占位生命周期状态）。"""
    cwd: str
    startedAt: int
    pid: int
    proc: object = None
    provider: str = ''
