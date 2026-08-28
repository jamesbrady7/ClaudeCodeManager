"""进程 / 终端工具（基础设施层，人人可调用）。"""
import os
import shutil

from PySide6.QtCore import QProcess

from ccui.infra.config import CONFIG_DIR, log

_WT_EXE = False  # None=未探测 / False=不可用 / str=wt.exe 路径


def _wt_path():
    """探测 Windows Terminal 的 wt.exe（App Execution Alias），缓存结果。"""
    global _WT_EXE
    if _WT_EXE is False:
        try:
            _WT_EXE = shutil.which('wt') or ''
        except Exception:
            _WT_EXE = ''
        if not _WT_EXE:
            log('未找到 wt.exe，回退 cmd.exe CREATE_NEW_CONSOLE（旧控制台）')
    return _WT_EXE or None


class _Delegated:
    """wt 启动的句柄包装：wt 客户端进程会立即退出（shell 由 WindowsTerminal
    服务端托管），不能用它判断会话存活——返回 pid=None / poll=None，
    让占位存活到 transcript 物化（或 TTL），避免假阴性「已退出」。"""

    pid = None

    def poll(self):
        return None


def spawn_terminal(args, cwd, env=None):
    """弹一个新终端窗口运行 cmd /k <args>。

    优先用 Windows Terminal（wt.exe）：避免 legacy conhost 的老样式、
    点阵字体渲染碎裂（章鱼/图标成方块）、以及 QuickEdit 点击挂起进程。
    找不到 wt 再回退 cmd.exe + CREATE_NEW_CONSOLE。

    env：追加到子进程环境（如 CC_INHERIT 传给 hook），None 表示不注入。
    返回进程句柄（或兜底的 pid / _Delegated 包装）。
    """
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    # projectPath 是正斜杠形式（C:/Users/...），normpath 归一为反斜杠再传给 wt -d / cwd
    run_cwd = os.path.normpath(cwd or CONFIG_DIR)
    wt = _wt_path()
    if wt:
        try:
            import subprocess
            # wt -d <dir> cmd.exe /k cc ...：实测 env 会透传给子进程；
            # wt 客户端秒退，故不返回 Popen 句柄而是 _Delegated
            subprocess.Popen([wt, '-d', run_cwd, 'cmd.exe', '/k'] + args,
                             env=full_env)
            return _Delegated()
        except Exception as e:
            log(f'wt 启动失败，回退 cmd：{e}')
    try:
        import subprocess
        return subprocess.Popen(['cmd.exe', '/k'] + args, cwd=run_cwd,
                                env=full_env, creationflags=subprocess.CREATE_NEW_CONSOLE)
    except Exception as e:
        log(f'subprocess spawn 失败: {e}')
    # 兜底：QProcess.startDetached（无句柄，仅能拿到 pid）
    try:
        qenv = [f'{k}={v}' for k, v in full_env.items()]
        ok, pid = QProcess.startDetached('cmd.exe', ['/k'] + args, run_cwd, qenv)
        return pid if ok else None
    except Exception as e:
        log(f'QProcess.startDetached 失败: {e}')
        return None
