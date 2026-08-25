"""生成 IExpress SED 配置并运行 iexpress 打包安装器。"""
import os
import subprocess

BASE = r'D:\ClaudeCode\installer'
OUT = os.path.join(BASE, 'ClaudeCodeManager-setup.exe')
SED = os.path.join(BASE, 'installer.sed')

# 收集所有文件（base 相对路径）
files = []
for root, _dirs, fnames in os.walk(BASE):
    for fn in fnames:
        full = os.path.join(root, fn)
        rel = os.path.relpath(full, BASE)
        files.append(rel)
files.sort()

# SED 内容
lines = []
lines.append('[Version]')
lines.append('Class=IEXPRESS')
lines.append('SEDVersion=3')
lines.append('[Options]')
lines.append('PackagePurpose=InstallApp')
lines.append('ShowInstallProgramWindow=1')
lines.append('HideExtractAnimation=1')
lines.append('UseLongFileName=1')
lines.append('InsideCompressed=0')
lines.append('CAB_FixedSize=0')
lines.append('CAB_ResvCodeSigning=0')
lines.append('RebootMode=Never')
lines.append('InstallPrompt=')
lines.append('DisplayLicense=')
lines.append('FinishMessage=')
lines.append('TargetName=ClaudeCodeManager-setup.exe')
lines.append('FriendlyName=Claude Code Manager')
lines.append('AppLaunched=setup.cmd')
lines.append('PostInstallCmd=<None>')
lines.append('AdminQuietInstCmd=')
lines.append('UserQuietInstCmd=')
lines.append('SourceFiles=SourceFiles')
lines.append('[Strings]')
for i, rel in enumerate(files):
    lines.append(f'FILE{i}="{os.path.join(BASE, rel)}"')
lines.append('[SourceFiles]')
lines.append(f'SourceFiles0={BASE}\\')
lines.append('[SourceFiles0]')
for i, rel in enumerate(files):
    lines.append(f'FILE{i}="{rel}"')

with open(SED, 'w', encoding='utf-8', newline='\r\n') as f:
    f.write('\r\n'.join(lines))
print(f'SED 生成: {len(files)} 个文件')

# 运行 IExpress（cwd=installer，输出到当前目录）
r = subprocess.run(['iexpress', '/N', '/Q', f'/C:{SED}'],
                   cwd=BASE, capture_output=True, text=True, encoding='gbk', timeout=300)
print('iexpress exit:', r.returncode)
if os.path.exists(OUT):
    print(f'安装器生成: {OUT} ({os.path.getsize(OUT)/1024/1024:.1f} MB)')
else:
    print('安装器未生成:', r.stdout[-500:], r.stderr[-500:])
