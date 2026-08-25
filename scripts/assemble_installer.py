"""组装安装包内容：便携 app + 启动器配置 → installer/package/。"""
import os
import shutil

ROOT = r'D:\ClaudeCode'
PKG = os.path.join(ROOT, 'installer', 'package')

EXCLUDED_ROLES = {'TEST2', 'TEST4', 'test', '测试', '唐睿溢'}  # 测试角色不入包
EXCLUDED_SKILLS = set()


def clean_copy(src, dst):
    """复制文件/目录（目录排除 __pycache__/.pyc）。"""
    if os.path.isdir(src):
        os.makedirs(dst, exist_ok=True)
        for e in os.listdir(src):
            if e in ('__pycache__',) or e.endswith('.pyc'):
                continue
            clean_copy(os.path.join(src, e), os.path.join(dst, e))
    else:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)


def main():
    if os.path.isdir(PKG):
        shutil.rmtree(PKG)
    os.makedirs(PKG, exist_ok=True)

    # 1. 便携 app（dist/cc-ui 扁平化：cc-ui.exe + _internal）
    dist = os.path.join(ROOT, 'dist', 'cc-ui')
    for e in os.listdir(dist):
        clean_copy(os.path.join(dist, e), os.path.join(PKG, e))

    # 2. 启动器脚本
    for f in ['cc.cmd', 'cc-role.ps1', 'cc-config-read.ps1', 'cc-provider.ps1',
              'cc-history.ps1', 'cc-clear.ps1', 'cc-backup.ps1', 'settings.json']:
        clean_copy(os.path.join(ROOT, f), os.path.join(PKG, f))

    # 2b. 卸载程序（随 package 落到安装目录根，uninstall.cmd 双击执行）
    clean_copy(os.path.join(ROOT, 'installer', 'uninstall.ps1'),
               os.path.join(PKG, 'uninstall.ps1'))
    clean_copy(os.path.join(ROOT, 'installer', 'uninstall.cmd'),
               os.path.join(PKG, 'uninstall.cmd'))

    # 3. roles：uidesigner + track-session.ps1（排除测试角色）
    roles_src = os.path.join(ROOT, 'roles')
    roles_dst = os.path.join(PKG, 'roles')
    for e in os.listdir(roles_src):
        if e in EXCLUDED_ROLES:
            continue
        clean_copy(os.path.join(roles_src, e), os.path.join(roles_dst, e))

    # 4. skills（全部）
    skills_src = os.path.join(ROOT, 'skills')
    for e in os.listdir(skills_src):
        if e in EXCLUDED_SKILLS:
            continue
        clean_copy(os.path.join(skills_src, e), os.path.join(PKG, 'skills', e))

    # 5. scripts（维护脚本）
    clean_copy(os.path.join(ROOT, 'scripts', 'backfill_skill_categories.py'),
               os.path.join(PKG, 'scripts', 'backfill_skill_categories.py'))

    # 统计
    total = sum(len(f) for _, _, fs in os.walk(PKG) for f in fs)
    nfiles = sum(len(fs) for _, _, fs in os.walk(PKG))
    print(f'package 就绪: {nfiles} 个文件, {total/1024/1024:.1f} MB -> {PKG}')
    print('顶层:', sorted(os.listdir(PKG))[:20])


if __name__ == '__main__':
    main()
