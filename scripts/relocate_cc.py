"""把 cc.cmd 的硬编码 D:\\ClaudeCode 改为相对 %~dp0（可移植）。"""
import io

p = r'D:\ClaudeCode\cc.cmd'
raw = io.open(p, encoding='utf-8').read()
new = raw.replace('D:\\ClaudeCode\\', '%~dp0')
new = new.replace('D:\\ClaudeCode/', '%~dp0')
# :ui 优先用便携 exe，否则退回 pythonw
new = new.replace(
    'start "" pythonw.exe "%~dp0cc-ui-qt.py"',
    'if exist "%~dp0cc-ui.exe" (start "" "%~dp0cc-ui.exe") else (start "" pythonw.exe "%~dp0cc-ui-qt.py")')
io.open(p, 'w', encoding='utf-8', newline='\n').write(new)
print('cc.cmd 已改为相对路径')
print('剩余 D:\\ClaudeCode 引用:', new.count('D:\\ClaudeCode'))
