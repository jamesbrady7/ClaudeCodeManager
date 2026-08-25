# ============================================================
#  cc-backup.ps1  —  备份 Claude Code 会话数据到配置目录之外
#
#  为什么: Claude Code 的 cleanupPeriodDays 保留清理会按 mtime
#  删除旧的会话记录（含 file-history / tasks），且官方没有关闭
#  开关。本脚本把会话数据复制到 D:\ClaudeCode-archive（配置目录
#  的兄弟目录，清理机制扫不到），作为独立兜底。
#
#  用法:
#    cc backup              # 默认保留 365 天
#    cc backup 180          # 自定义保留天数
#    cc backup 0            # 不清理归档（会一直增长）
#
#  归档策略:
#    - 用 /E 增量复制（不删归档里已有的内容）
#    - 清理「源目录里已不存在、且归档副本超过 RetentionDays 天」的旧文件
#    - 源里还存在的会话不会被清（防止闲置会话被误删时归档也丢了）
#    - 所以归档体积 ≈ 当前会话 + 最近 RetentionDays 天内被删过的会话
# ============================================================

param(
    [int]$RetentionDays = 365
)

$ErrorActionPreference = 'Stop'

$configDir = $env:CLAUDE_CONFIG_DIR
if (-not $configDir) { $configDir = "D:\ClaudeCode" }
$dest = "D:\ClaudeCode-archive"

# 会话数据目录（增量复制，保留历史）
$subdirs = @('projects', 'file-history', 'tasks', 'roles', 'agents')

$exitCode = 0
foreach ($sub in $subdirs) {
    $src = Join-Path $configDir $sub
    if (-not (Test-Path $src)) { continue }
    Write-Host "备份: $sub ..." -ForegroundColor Cyan
    robocopy $src (Join-Path $dest $sub) /E /R:2 /W:2 /NFL /NDL /NJH /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {
        Write-Warning "robocopy 失败 ($sub)：退出码 $LASTEXITCODE"
        $exitCode = 1
    }
}

# prompt 历史（也会被清理修剪，值得一起备份）
$historySrc = Join-Path $configDir 'history.jsonl'
if (Test-Path $historySrc) {
    robocopy $configDir $dest 'history.jsonl' /R:2 /W:2 /NFL /NDL /NJH /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {
        Write-Warning "robocopy 失败 (history.jsonl)：退出码 $LASTEXITCODE"
        $exitCode = 1
    }
}

# ---------- 归档保留：清掉「源里已无、且归档副本过旧」的文件 ----------
$purged = 0
if ($RetentionDays -gt 0) {
    $cutoff = (Get-Date).AddDays(-$RetentionDays)
    $files = Get-ChildItem -Path $dest -Recurse -File -ErrorAction SilentlyContinue
    foreach ($f in $files) {
        if ($f.LastWriteTime -ge $cutoff) { continue }
        # 把归档路径换算回源路径（archive -> configDir）
        $rel = $f.FullName.Substring($dest.Length).TrimStart('\')
        $srcPath = Join-Path $configDir $rel
        if (-not (Test-Path $srcPath)) {
            Remove-Item $f.FullName -Force
            $purged++
        }
    }
    # 顺手清空只剩空目录的归档目录
    Get-ChildItem -Path $dest -Recurse -Directory -ErrorAction SilentlyContinue |
        Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object {
            if (-not (Get-ChildItem -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue)) {
                Remove-Item $_.FullName -Force
            }
        }
}

# ---------- 汇总 ----------
$sizeMB = [math]::Round((Get-ChildItem -Path $dest -Recurse -File -ErrorAction SilentlyContinue |
    Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host ("归档大小: {0} MB" -f $sizeMB) -ForegroundColor Cyan
if ($purged -gt 0) {
    Write-Host ("已清理 {0} 个超过 {1} 天且源里已不存在的归档文件" -f $purged, $RetentionDays) -ForegroundColor Yellow
}

if ($exitCode -eq 0) {
    Write-Host "备份完成 → $dest" -ForegroundColor Green
} else {
    Write-Host "备份完成（有警告）→ $dest" -ForegroundColor Yellow
}
exit $exitCode
