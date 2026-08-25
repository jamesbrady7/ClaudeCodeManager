# ============================================================
#  ClaudeCodeManager 卸载程序（随安装落在安装目录根下）
#  运行: 双击（图形询问）或命令行
#    uninstall.ps1 -Keep       静默保留数据后卸载
#    uninstall.ps1 -Wipe       静默完全卸载
#    uninstall.ps1 -Silent     无弹窗（需配合 -Keep / -Wipe）
#
#  行为:
#    · 保留数据模式：用户数据（会话/角色/技能/API 密钥等）复制到
#      %LOCALAPPDATA%\ClaudeCodeManager-data，下次安装时自动恢复。
#    · 完全卸载：删除安装目录内所有内容（含数据）。
#    · 两种模式都清理：桌面快捷方式、CLAUDE_CONFIG_DIR、用户 PATH 条目。
# ============================================================
param(
    [switch]$Keep,
    [switch]$Wipe,
    [switch]$Silent
)
Add-Type -AssemblyName System.Windows.Forms
$ErrorActionPreference = 'Stop'

$dest = $PSScriptRoot
$backupRoot = Join-Path $env:LOCALAPPDATA 'ClaudeCodeManager-data'
$lnkName = 'Claude Code 管理.lnk'

# 保留的数据清单（与 setup.ps1 恢复逻辑一致）
$userData = @('cc-config.json', 'session-providers.json', 'ui-state.json', '.claude.json',
              'projects', 'sessions', 'telemetry', 'history.jsonl', 'file-history',
              'tasks', 'inherit', 'backups', 'cache', 'shell-snapshots', 'session-env',
              'roles', 'skills')


function Invoke-Cleanup {
    # 清理桌面快捷方式
    $desktop = [Environment]::GetFolderPath('Desktop')
    $lnk = Join-Path $desktop $lnkName
    if (Test-Path $lnk) { Remove-Item $lnk -Force }
    # 清理 CLAUDE_CONFIG_DIR（若指向本安装目录）
    $ccd = [Environment]::GetEnvironmentVariable('CLAUDE_CONFIG_DIR', 'User')
    if ($ccd -and $ccd -ieq $dest) {
        [Environment]::SetEnvironmentVariable('CLAUDE_CONFIG_DIR', $null, 'User')
    }
    # 从用户 PATH 移除本目录及其下子目录（如便携 node）
    $up = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($up) {
        $kept = @($up -split ';' | Where-Object {
            $_ -and $_ -ine $dest -and $_ -notlike "$dest\*"
        })
        [Environment]::SetEnvironmentVariable('Path', ($kept -join ';'), 'User')
    }
}


# ---- 决定动作 ----
$action = ''
if ($Keep) { $action = 'keep' }
elseif ($Wipe) { $action = 'wipe' }
if ($action -eq '' -and -not $Silent) {
    $msg = "卸载 Claude Code 管理器？`n`n" +
           "· 是  —— 保留数据后卸载`n" +
           "   会话 / 角色 / 技能 / API 密钥将备份到:`n   $backupRoot`n" +
           "   下次安装新版时自动恢复。`n`n" +
           "· 否  —— 完全卸载（删除本目录内所有数据）`n" +
           "· 取消"
    $r = [System.Windows.Forms.MessageBox]::Show($msg, '卸载 Claude Code 管理器',
        'YesNoCancel', 'Question', 'Cancel')
    if ($r -eq 'Yes') { $action = 'keep' }
    elseif ($r -eq 'No') { $action = 'wipe' }
    else { exit 0 }
}
if ($action -eq '') { exit 0 }

if (-not (Test-Path $dest)) { Write-Host '安装目录不存在。'; exit 0 }

# ---- 保留数据模式：复制数据到备份目录 ----
if ($action -eq 'keep') {
    try {
        New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
        foreach ($name in $userData) {
            $src = Join-Path $dest $name
            if (Test-Path $src) {
                $dst = Join-Path $backupRoot $name
                # 旧备份目标先删再复制（否则 Copy-Item -Recurse 会嵌套成 backup\roles\roles\）
                if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
                Copy-Item $src $dst -Recurse -Force
            }
        }
        if (-not $Silent) {
            [System.Windows.Forms.MessageBox]::Show(
                "数据已备份到:`n$backupRoot`n`n下次安装新版时自动恢复。现在开始卸载…",
                '正在卸载', 'OK', 'Information') | Out-Null
        }
    } catch {
        if (-not $Silent) {
            [System.Windows.Forms.MessageBox]::Show(
                "备份数据失败：$($_.Exception.Message)`n已中止卸载，未删除任何文件。",
                '错误', 'OK', 'Error') | Out-Null
        }
        exit 1
    }
}

# ---- 清理环境 + 删除目录 ----
Invoke-Cleanup
try {
    Remove-Item $dest -Recurse -Force
} catch {
    if (-not $Silent) {
        [System.Windows.Forms.MessageBox]::Show(
            "删除目录失败：$($_.Exception.Message)`n环境变量/快捷方式已清理，请手动删除 $dest",
            '提示', 'OK', 'Warning') | Out-Null
    }
}

# ---- 完全卸载后：若有历史备份，询问是否一并删除 ----
if ($action -eq 'wipe' -and (Test-Path $backupRoot) -and -not $Silent) {
    $r2 = [System.Windows.Forms.MessageBox]::Show(
        "检测到历史保留的数据备份:`n$backupRoot`n`n是否也一并删除？", '历史备份',
        'YesNo', 'Question', 'No')
    if ($r2 -eq 'Yes') { Remove-Item $backupRoot -Recurse -Force }
}

if (-not $Silent) {
    [System.Windows.Forms.MessageBox]::Show('Claude Code 管理器已卸载。', '完成', 'OK', 'Information') | Out-Null
}
