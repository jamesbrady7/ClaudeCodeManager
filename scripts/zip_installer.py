"""压缩安装器内容（package/ + setup.ps1 + setup.cmd）→ installer-data.zip。"""
import os
import zipfile

SRC = r'D:\ClaudeCode\installer'
OUT = os.path.join(SRC, 'installer-data.zip')


def main():
    if os.path.exists(OUT):
        os.remove(OUT)
    items = [('package', os.path.join(SRC, 'package')),
             ('setup.ps1', os.path.join(SRC, 'setup.ps1')),
             ('setup.cmd', os.path.join(SRC, 'setup.cmd')),
             ('wizard.ps1', os.path.join(SRC, 'wizard.ps1'))]
    # uninstall.ps1 由 assemble_installer.py 放进 package/ 根，随 package 整体打包
    with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as zf:
        for arcname, abspath in items:
            if os.path.isdir(abspath):
                for root, _dirs, files in os.walk(abspath):
                    for f in files:
                        full = os.path.join(root, f)
                        rel = os.path.relpath(full, SRC).replace(os.sep, '/')
                        zf.write(full, rel)
            else:
                zf.write(abspath, arcname)
    print(f'zip: {os.path.getsize(OUT)/1024/1024:.1f} MB, '
          f'{len(zipfile.ZipFile(OUT).namelist())} 成员 -> {OUT}')


if __name__ == '__main__':
    main()
