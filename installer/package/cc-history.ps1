# Claude Code session history viewer
# Lists past sessions stored under D:\ClaudeCode\projects in a human-readable form.

$ErrorActionPreference = 'SilentlyContinue'

# Resolve config root from environment or default
$configDir = $env:CLAUDE_CONFIG_DIR
if (-not $configDir) { $configDir = "D:\ClaudeCode" }
$root = Join-Path $configDir "projects"

if (-not (Test-Path $root)) {
    Write-Host "No session directory found: $root"
    exit 0
}

# 只列真实会话：文件名须为 UUID。子代理记录（agent-*.jsonl）
# 存在父会话的子目录里，不是可恢复的会话，一并过滤掉。
$uuidRe = '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
$files = Get-ChildItem -Path $root -Recurse -Filter *.jsonl |
    Where-Object { $_.BaseName -match $uuidRe } |
    Sort-Object LastWriteTime -Descending

if (-not $files -or $files.Count -eq 0) {
    Write-Host "No past sessions found."
    exit 0
}

$rows = @()

foreach ($f in $files) {
    $sessionId = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
    $lines = [System.IO.File]::ReadAllLines($f.FullName, [System.Text.Encoding]::UTF8)

    $title = "(empty session)"
    $firstUserTime = $null
    $lastTime = $null
    $userCount = 0
    $assistantCount = 0
    $cwd = ""

    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $o = $null
        try { $o = $line | ConvertFrom-Json } catch { continue }
        if ($null -eq $o) { continue }

        if ($o.timestamp) { $lastTime = $o.timestamp }

        if ($o.type -eq 'user') {
            $userCount++
            if (-not $firstUserTime) { $firstUserTime = $o.timestamp }
            if ($title -eq "(empty session)") {
                $c = $o.message.content
                if ($c -is [string]) {
                    $title = $c
                } elseif ($c -is [System.Array]) {
                    # content blocks: find first text block
                    foreach ($blk in $c) {
                        if ($blk.type -eq 'text' -and $blk.text) {
                            $title = $blk.text
                            break
                        }
                    }
                }
            }
        }
        if ($o.type -eq 'assistant') { $assistantCount++ }
        if ($o.cwd -and -not $cwd) { $cwd = $o.cwd }
    }

    # Clean title: single line, trimmed
    $title = ($title -replace '\s+', ' ').Trim()
    if ($title.Length -gt 48) { $title = $title.Substring(0, 48) + "..." }

    # human-friendly time
    $when = ""
    if ($lastTime) {
        try {
            $dt = [DateTime]::Parse($lastTime).ToLocalTime()
            $when = $dt.ToString("yyyy-MM-dd HH:mm")
        } catch { $when = $lastTime }
    }

    $rows += [PSCustomObject]@{
        Time       = $when
        Turns      = "$userCount Q / $assistantCount A"
        Directory  = $cwd
        SessionId  = $sessionId
        Title      = $title
    }
}

Write-Host ""
Write-Host "=== Claude Code Session History ===" -ForegroundColor Cyan
Write-Host "Total sessions: $($rows.Count)"
Write-Host ""

$num = 0
foreach ($r in $rows) {
    $num++
    Write-Host "[$num]" -ForegroundColor Yellow -NoNewline
    Write-Host (" " + $r.Time + "  " + $r.Turns) -NoNewline
    if ($r.Directory) { Write-Host ("  dir=" + $r.Directory) -NoNewline }
    Write-Host ""
    Write-Host "    " -NoNewline
    Write-Host $r.Title -ForegroundColor White
    Write-Host ("    resume: cc resume " + $r.SessionId) -ForegroundColor DarkGray
    Write-Host ""
}

Write-Host "To resume a session:  cc resume <sessionId>" -ForegroundColor Cyan
Write-Host "For interactive picker:  cc resume" -ForegroundColor Cyan
Write-Host ""