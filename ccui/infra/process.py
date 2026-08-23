"""进程 / 终端工具（基础设施层，人人可调用）。"""
import os

from PySide6.QtCore import QProcess

from ccui.infra.config import CONFIG_DIR, log


def spawn_terminal(args, cwd, env=None):
    """弹一个新控制台窗口运行 cmd /k <args>。返回 Popen 句柄（可监控退出）。

    env：追加到子进程环境（如 CC_INHERIT 传给 hook），None 表示不注入。
    """
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    try:
        import subprocess
        return subprocess.Popen(['cmd.exe', '/k'] + args, cwd=cwd or CONFIG_DIR,
                                env=full_env, creationflags=subprocess.CREATE_NEW_CONSOLE)
    except Exception as e:
        log(f'subprocess spawn 失败: {e}')
    # 兜底：QProcess.startDetached（无句柄，仅能拿到 pid）
    try:
        qenv = [f'{k}={v}' for k, v in full_env.items()]
        ok, pid = QProcess.startDetached('cmd.exe', ['/k'] + args, cwd or CONFIG_DIR, qenv)
        return pid if ok else None
    except Exception as e:
        log(f'QProcess.startDetached 失败: {e}')
        return None
