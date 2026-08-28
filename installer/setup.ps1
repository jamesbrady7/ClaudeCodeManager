# ============================================================
#  ClaudeCodeManager 安装脚本（由图形安装向导调用，无需管理员）
#  参数:
#    -Dest        安装目录（默认 %LOCALAPPDATA%\ClaudeCodeManager）
#    -ConfigPath  用户提供的 cc-config.json（可选，含 API 密钥；给了就装成 Dest\cc-config.json）
#  行为:
#    · 便携应用 cc-ui.exe + 启动器配置（cc/cc-role/roles/skills）
#    · 生成 settings.json（SessionStart hook 指向安装目录）
#    · cc-config.json：用户给了则用之；否则已有保留、没有则生成空模板
#    · 设 CLAUDE_CONFIG_DIR + 把安装目录加入用户 PATH
#    · 桌面快捷方式（章鱼图标）
#    · 检查 Claude Code，缺失则自动安装
# ============================================================
param(
    [string]$Dest = '',
    [string]$ConfigPath = ''
)
$ErrorActionPreference = 'Stop'
$src  = $PSScriptRoot
$dest = if ($Dest) { $Dest } else { Join-Path $env:LOCALAPPDATA 'ClaudeCodeManager' }

Write-Host ''
Write-Host 'Claude Code 管理器 安装' -ForegroundColor Cyan
Write-Host ('安装目录: ' + $dest)

# ---- 1. 安装应用 + 启动器（覆盖升级：保留用户数据/密钥/自定义角色技能，绝不整删）----
$pkgSrc = Join-Path $src 'package'
$isUpgrade = Test-Path $dest
New-Item -ItemType Directory -Force -Path $dest | Out-Null

# 用户数据/配置：升级时保留（transcript、运行态、历史、密钥、自定义角色技能）
$preserve = @('projects', 'sessions', 'telemetry', 'history.jsonl', 'file-history',
              'tasks', 'inherit', 'backups', 'cache', 'shell-snapshots', 'session-env',
              'cc-config.json', 'ui-state.json', 'session-providers.json')

foreach ($child in Get-ChildItem $pkgSrc -Force) {
    $target = Join-Path $dest $child.Name
    if ($child.Name -in $preserve) {
        # 用户数据/配置：仅首次安装时复制（包内一般不含），升级保留原样
        if (-not $isUpgrade) { Copy-Item $child.FullName $target -Recurse -Force }
        continue
    }
    if ($child.Name -in @('roles', 'skills')) {
        # 合并：覆盖包内自带的条目，保留用户新建的（不清除）
        foreach ($sub in Get-ChildItem $child.FullName) {
            Copy-Item $sub.FullName (Join-Path $target $sub.Name) -Recurse -Force
        }
        continue
    }
    # 应用 + 启动器脚本：直接覆盖
    Copy-Item $child.FullName $target -Recurse -Force
}
if ($isUpgrade) {
    Write-Host '  已覆盖升级应用与配置（保留你的数据/密钥/自定义角色）' -ForegroundColor DarkGray
} else {
    Write-Host '  已复制应用与配置' -ForegroundColor DarkGray
}

# ---- 1a2. 恢复上次「保留数据」卸载留下的备份（%LOCALAPPDATA%\ClaudeCodeManager-data）----
# 数据优先覆盖包内内容（用户自定义角色/技能/密钥/会话都要回来）。
$backupRoot = Join-Path $env:LOCALAPPDATA 'ClaudeCodeManager-data'
if (Test-Path $backupRoot) {
    try {
        foreach ($item in Get-ChildItem $backupRoot -Force) {
            $target = Join-Path $dest $item.Name
            if ($item.PSIsContainer) {
                # 目录：逐项合并（目标已存在时不能 Copy-Item dir destDir -Recurse，
                # 否则会嵌套成 dest\roles\roles\；必须逐个子项复制）
                New-Item -ItemType Directory -Force -Path $target | Out-Null
                Get-ChildItem $item.FullName -Force | ForEach-Object {
                    Copy-Item $_.FullName (Join-Path $target $_.Name) -Recurse -Force
                }
            } else {
                Copy-Item $item.FullName $target -Force
            }
        }
        Write-Host '  已恢复上次保留的数据（会话/角色/技能/API 密钥）' -ForegroundColor DarkGray
        Remove-Item $backupRoot -Recurse -Force
    } catch {
        Write-Host ("  恢复上次备份失败: " + $_.Exception.Message) -ForegroundColor Yellow
    }
}

# ---- 1b. 用户提供的 cc-config.json → 装为 Dest\cc-config.json（后续模板不会覆盖）----
if ($ConfigPath -and (Test-Path $ConfigPath)) {
    Copy-Item $ConfigPath (Join-Path $dest 'cc-config.json') -Force
    Write-Host ('  已使用你提供的 provider 配置: ' + $ConfigPath) -ForegroundColor DarkGray
}

# ---- 2. 生成 settings.json（SessionStart hook 指向安装目录的 track-session.ps1）----
$hookCfg = @{
    skipDangerousModePermissionPrompt = $true
    theme  = 'dark'
    autoUpdates = $false
    cleanupPeriodDays = 99999
    hooks  = @{
        SessionStart = @(
            @{ hooks = @(
                @{ type = 'command'; command = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$dest\roles\track-session.ps1`"" }
            ) }
        )
    }
}
$hookCfg | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $dest 'settings.json') -Encoding UTF8

# ---- 3. cc-config.json 模板（无密钥，用户自填）----
$cfgPath = Join-Path $dest 'cc-config.json'
if (-not (Test-Path $cfgPath)) {
    $template = @{
        'provider config' = @{
            'default provider' = 'deepseek'
            deepseek   = @{ baseUrl = 'https://api.deepseek.com/anthropic'; apiKey = ''; model = 'deepseek-v4-flash'; fastModel = 'deepseek-v4-flash' }
            glm        = @{ baseUrl = 'https://open.bigmodel.cn/api/anthropic'; apiKey = ''; model = 'glm-5.2'; fastModel = 'glm-4.7' }
            qwen       = @{ baseUrl = 'https://dashscope.aliyuncs.com/apps/anthropic'; apiKey = ''; model = ''; fastModel = '' }
            kimi       = @{ baseUrl = 'https://api.moonshot.cn/anthropic'; apiKey = ''; model = ''; fastModel = '' }
            minimax    = @{ baseUrl = 'https://api.minimaxi.com/anthropic'; apiKey = ''; model = ''; fastModel = '' }
            xiaomi     = @{ baseUrl = 'https://api.xiaomimimo.com/anthropic'; apiKey = ''; model = ''; fastModel = '' }
            anthropic  = @{ baseUrl = 'https://api.anthropic.com'; apiKey = ''; model = ''; fastModel = '' }
        }
    }
    $template | ConvertTo-Json -Depth 5 | Set-Content $cfgPath -Encoding UTF8
    Write-Host '  已生成 cc-config.json 模板（请填入你的 API 密钥）' -ForegroundColor DarkGray
}

# ---- 4. 环境变量：CLAUDE_CONFIG_DIR + PATH ----
[Environment]::SetEnvironmentVariable('CLAUDE_CONFIG_DIR', $dest, 'User')
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -notlike "*$dest*") {
    [Environment]::SetEnvironmentVariable('Path', "$dest;$userPath", 'User')
    Write-Host '  已设 CLAUDE_CONFIG_DIR 并把安装目录加入 PATH' -ForegroundColor DarkGray
}

# ---- 5. 桌面快捷方式（章鱼图标来自 cc-ui.exe）----
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = Join-Path $desktop 'Claude Code 管理.lnk'
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = Join-Path $dest 'cc-ui.exe'
$sc.IconLocation = "$(Join-Path $dest 'cc-ui.exe'),0"
$sc.WorkingDirectory = $dest
$sc.Description = 'Claude Code 会话管理'
$sc.Save()
Write-Host '  已创建桌面快捷方式「Claude Code 管理」' -ForegroundColor DarkGray

# ---- 6. 检查/安装 Claude Code（任意机器：无 claude → 自动装，缺 Node → 先装便携 Node）----
$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
    Write-Host ("  Claude Code 已安装: " + $claude.Source) -ForegroundColor Green
} else {
    Write-Host '  未检测到 Claude Code，尝试自动安装…' -ForegroundColor Yellow
    $node = Get-Command node -ErrorAction SilentlyContinue
    if (-not $node) {
        Write-Host '  未检测到 Node.js，先自动安装便携版 Node.js（免管理员）…' -ForegroundColor Yellow
        try {
            $nodeVer = 'v20.11.1'
            $nodeUrl = "https://nodejs.org/dist/$nodeVer/node-$nodeVer-win-x64.zip"
            $nodeZip = Join-Path $env:TEMP 'node-install.zip'
            $nodeHome = Join-Path $dest 'node'
            Invoke-WebRequest -Uri $nodeUrl -OutFile $nodeZip
            Expand-Archive -Path $nodeZip -DestinationPath $nodeHome -Force
            $nodeDir = Join-Path $nodeHome "node-$nodeVer-win-x64"
            # 便携 Node 加入用户 PATH
            $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
            if ($userPath -notlike "*$nodeDir*") {
                [Environment]::SetEnvironmentVariable('Path', "$nodeDir;$userPath", 'User')
            }
            $env:Path = "$nodeDir;" + $env:Path
            $node = Get-Command node -ErrorAction SilentlyContinue
            Write-Host '  便携版 Node.js 已就绪。' -ForegroundColor DarkGray
        } catch {
            Write-Host ("  安装 Node.js 失败: " + $_.Exception.Message) -ForegroundColor Red
        }
    }
    if ($node) {
        try {
            npm install -g @anthropic-ai/claude-code
            # 刷新 PATH 以便 claude 可被识别
            $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
            $claude = Get-Command claude -ErrorAction SilentlyContinue
            if ($claude) {
                Write-Host ("  Claude Code 安装完成: " + $claude.Source) -ForegroundColor Green
            } else {
                Write-Host '  Claude Code 已安装（请新开终端后使用 claude 命令）。' -ForegroundColor Green
            }
        } catch {
            Write-Host ("  npm 安装失败: " + $_.Exception.Message) -ForegroundColor Red
            Write-Host '  请手动运行: npm install -g @anthropic-ai/claude-code'
        }
    } else {
        Write-Host '  Node.js 安装失败，无法自动安装 Claude Code。' -ForegroundColor Red
        Write-Host '  请联网后手动: 安装 Node.js 并运行 npm install -g @anthropic-ai/claude-code'
    }
}

Write-Host ''
Write-Host '安装完成！桌面已创建「Claude Code 管理」快捷方式。' -ForegroundColor Green
Write-Host '在终端可用 cc 命令（cc role / cc ui / cc resume 等）。'
Start-Sleep 3
