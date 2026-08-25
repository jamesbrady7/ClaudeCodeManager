"""ClaudeCodeManager 安装器（PyInstaller 单文件、纯图形无控制台）。

运行时解压 installer-data.zip 到临时目录并启动 wizard.ps1（图形安装向导）。
无控制台，出错写日志到用户主目录便于排查。
"""
import os
import sys
import tempfile
import zipfile
import shutil
import subprocess

ERROR_LOG = os.path.join(os.path.expanduser('~'), 'ccm-install-error.log')


def resource_path(name):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def log_error(msg):
    try:
        with open(ERROR_LOG, 'w', encoding='utf-8') as f:
            f.write(f'{msg}\n')
    except Exception:
        pass


def main():
    zip_path = resource_path('installer-data.zip')
    if not os.path.exists(zip_path):
        log_error('找不到安装数据 installer-data.zip')
        return
    tmp = tempfile.mkdtemp(prefix='ccm-install-')
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(tmp)
        wizard = os.path.join(tmp, 'wizard.ps1')
        r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                            '-File', wizard],
                           cwd=tmp)
        if r.returncode != 0:
            log_error(f'wizard.ps1 退出码 {r.returncode}')
    except Exception as e:
        log_error(repr(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
