# Claude Code session cleaner
# Usage:
#   cc clear               -> list sessions and show how to delete
#   cc clear <sessionId>   -> delete one session (full id or unique prefix)
#   cc clear all           -> delete ALL sessions
#
# Besides deleting the session .jsonl, it also:
#   - removes matching lines from history.jsonl (prompt history)
#   - clears lastSessionId in .claude.json if it pointed to a deleted session

$ErrorActionPreference = 'Stop'

# Resolve config root
$configDir = $env:CLAUDE_CONFIG_DIR
if (-not $configDir) { $configDir = "D:\ClaudeCode" }
$root = Join-Path $configDir "projects"

$target = $args[0]  # sessionId | all | empty

# --- gather existing session files ---
# 只收真实会话：文件名须为 UUID。子代理记录（agent-*.jsonl）随父会话删除，
# 不单独列出，避免出现无法恢复的条目。
$uuidRe = '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
$files = @()
if (Test-Path $root) {
    $files = Get-ChildItem -Path $root -Recurse -Filter *.jsonl |
        Where-Object { $_.BaseName -match $uuidRe }
}

if ($files.Count -eq 0) {
    Write-Host "No sessions found."
    exit 0
}

# --- list mode ---
if (-not $target) {
    Write-Host ""
    Write-Host "=== Sessions (to delete) ===" -ForegroundColor Cyan
    Write-Host "Total: $($files.Count)"
    Write-Host ""
    foreach ($f in $files) {
        $sid = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
        Write-Host ("  " + $sid) -ForegroundColor White
    }
    Write-Host ""
    Write-Host "Delete a single session:" -ForegroundColor Yellow
    Write-Host "  cc clear <sessionId>" -ForegroundColor Gray
    Write-Host "Delete ALL sessions:" -ForegroundColor Yellow
    Write-Host "  cc clear all" -ForegroundColor Gray
    Write-Host ""
    exit 0
}

# --- resolve which files to delete ---
$toDelete = @()

if (($target -eq 'all') -or ($target -eq '-a') -or ($target -eq '--all')) {
    $toDelete = $files
} else {
    # match by full id, or by unique prefix
    $matches = @($files | Where-Object {
        $sid = [System.IO.Path]::GetFileNameWithoutExtension($_.Name)
        $sid -eq $target -or $sid.StartsWith($target)
    })

    if ($matches.Count -eq 0) {
        Write-Host "No session matches '$target'." -ForegroundColor Red
        Write-Host "Run 'cc hist' or 'cc clear' to list sessions." -ForegroundColor Gray
        exit 1
    }
    if ($matches.Count -gt 1) {
        Write-Host "Ambiguous prefix '$target' matches ${($matches.Count)} sessions:" -ForegroundColor Red
        foreach ($m in $matches) {
            Write-Host ("  " + [System.IO.Path]::GetFileNameWithoutExtension($m.Name))
        }
        Write-Host "Use the full session id." -ForegroundColor Gray
        exit 1
    }
    $toDelete = $matches
}

# --- collect deleted session ids ---
$deletedIds = @()
foreach ($f in $toDelete) {
    $sid = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
    $deletedIds += $sid
    Remove-Item $f.FullName -Force
    # 顺带删掉该会话的子目录（subagents 等），让子代理随父会话一起消失
    $sub = Join-Path $f.DirectoryName $sid
    if (Test-Path $sub) { Remove-Item $sub -Recurse -Force }
    Write-Host ("Deleted: " + $sid) -ForegroundColor Green
}

# --- clean history.jsonl (prompt history) ---
$historyFile = Join-Path $configDir "history.jsonl"
if (Test-Path $historyFile) {
    $lines = [System.IO.File]::ReadAllLines($historyFile, [System.Text.Encoding]::UTF8)
    $kept = @()
    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $ok = $true
        foreach ($sid in $deletedIds) {
            if ($line -like "*$sid*") { $ok = $false; break }
        }
        if ($ok) { $kept += $line }
    }
    $joined = ($kept -join [Environment]::NewLine)
    [System.IO.File]::WriteAllText($historyFile, $joined, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Cleaned history.jsonl" -ForegroundColor Green
}

# --- clean lastSessionId references in .claude.json ---
$claudeJson = Join-Path $configDir ".claude.json"
if (Test-Path $claudeJson) {
    try {
        $raw = [System.IO.File]::ReadAllText($claudeJson, [System.Text.Encoding]::UTF8)
        $cfg = $raw | ConvertFrom-Json
        $changed = $false

        if ($cfg.projects) {
            foreach ($prop in $cfg.projects.PSObject.Properties) {
                $project = $prop.Value
                if ($project.lastSessionId -and ($deletedIds -contains $project.lastSessionId)) {
                    $project.lastSessionId = $null
                    $changed = $true
                }
            }
        }

        if ($changed) {
            $json = $cfg | ConvertTo-Json -Depth 20
            [System.IO.File]::WriteAllText($claudeJson, $json, (New-Object System.Text.UTF8Encoding($false)))
            Write-Host "Updated .claude.json (cleared stale lastSessionId)" -ForegroundColor Green
        }
    } catch {
        Write-Host "Warning: could not update .claude.json: $_" -ForegroundColor Yellow
    }
}

Write-Host ("Done. Removed {0} session(s)." -f $deletedIds.Count) -ForegroundColor Cyan