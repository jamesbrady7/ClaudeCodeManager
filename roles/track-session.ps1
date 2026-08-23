# ============================================================
#  track-session.ps1  —  SessionStart hook：记录角色会话 + 输出知识/继承读取指令
#
#  通过 settings.json 的 hooks.SessionStart 注册。每次会话启动时
#  运行一次。CC_ROLE 与 CC_INHERIT 都为空（普通会话）时零开销退出。
#
#  职责:
#   1. 若 CC_ROLE 已设置且角色目录存在，把本次 session_id 追加到
#      roles\<role>\sessions.jsonl（按 id 去重，resume/fork/clear
#      生成的新 id 也会记录）。
#   2. 向 stdout 输出中文读取指令 —— 该输出会被注入到会话上下文：
#      · CC_ROLE  → 人设 + 技能 + 知识库（+ 角色 inherit.md）
#      · CC_INHERIT → 让普通新建会话先读继承摘要文件
#
#  注意: 不要 Write-Host（stdout 会变成上下文）；全程 try/catch 并
#  永远 exit 0（非零退出会作为错误显示给用户）。
# ============================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 读取 SKILL.md 的 description（frontmatter）
function Get-SkillDescription([string]$skillPath) {
    if (-not (Test-Path $skillPath)) { return '' }
    try {
        $content = Get-Content $skillPath -Raw -Encoding UTF8
        if ($content -match '(?ms)^---\r?\n(.*?)\r?\n---') {
            $front = $Matches[1]
            if ($front -match '(?m)^description:\s*(.*)$') { return $Matches[1].Trim() }
        }
    } catch { }
    return ''
}

# 根据技能名生成技能段：角色专属带路径引用，全局列名字+描述
function Get-RoleSkillsText {
    param([string]$RoleName, [string[]]$Skills)
    if (-not $Skills) { return '' }
    $lines = @('## 特化技能', '你掌握以下技能：')
    $found = 0
    foreach ($skill in $Skills) {
        if ([string]::IsNullOrWhiteSpace($skill)) { continue }
        $rolePath   = Join-Path (Join-Path (Join-Path $configDir 'roles') $RoleName) "skills\$skill\SKILL.md"
        $globalPath = Join-Path (Join-Path $configDir 'skills') "$skill\SKILL.md"
        $path = $null
        $source = ''
        if (Test-Path $rolePath)     { $path = $rolePath;     $source = 'role' }
        elseif (Test-Path $globalPath) { $path = $globalPath; $source = 'global' }
        if (-not $path) { continue }
        $desc = Get-SkillDescription $path
        if ([string]::IsNullOrWhiteSpace($desc)) { $desc = '（无描述）' }
        if ($source -eq 'role') {
            $lines += "- **$skill**（$desc）：执行相关任务时先 Read $path 并遵循其指令。"
        } else {
            $lines += "- **$skill**（$desc）：相关任务时调用该技能。"
        }
        $found++
    }
    if ($found -eq 0) { return '' }
    return ($lines -join "`n")
}

try {
    # ---- 读 stdin 的 hook 载荷 ----
    $json = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($json)) { exit 0 }
    $payload = $json | ConvertFrom-Json

    $role = [string]$env:CC_ROLE
    $inheritPath = [string]$env:CC_INHERIT
    if ([string]::IsNullOrWhiteSpace($role) -and [string]::IsNullOrWhiteSpace($inheritPath)) { exit 0 }

    $configDir = $env:CLAUDE_CONFIG_DIR
    if (-not $configDir) { $configDir = 'D:\ClaudeCode' }
    $roleDir = Join-Path (Join-Path $configDir 'roles') $role

    $sessionId = [string]$payload.session_id
    if ($sessionId -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') { exit 0 }

    $isRole = (-not [string]::IsNullOrWhiteSpace($role)) -and (Test-Path $roleDir)
    if ($isRole) {
        # ---- 角色会话：去重后追加记录 ----
        $trackFile = Join-Path $roleDir 'sessions.jsonl'
        $already = $false
        if (Test-Path $trackFile) {
            $ids = @(Get-Content $trackFile -Encoding UTF8 -ErrorAction SilentlyContinue | ForEach-Object {
                if ($_.Trim()) { try { ($_ | ConvertFrom-Json).session_id } catch { $null } }
            } | Where-Object { $_ })
            if ($ids -contains $sessionId) { $already = $true }
        }
        if (-not $already) {
            $record = @{
                session_id = $sessionId
                timestamp  = (Get-Date).ToUniversalTime().ToString('o')
                cwd        = [string]$payload.cwd
            }
            $line = (($record | ConvertTo-Json -Compress)) + "`n"
            [System.IO.File]::AppendAllText($trackFile, $line, (New-Object System.Text.UTF8Encoding($false)))
        }
    }

    # ---- 输出指令（注入会话上下文）：角色 = 人设 + 技能 + 知识库；普通继承 = CC_INHERIT ----
    $directive = ''
    if ($isRole) {
        $knowledge = Join-Path $roleDir 'knowledge.md'
        $inherit   = Join-Path $roleDir 'inherit.md'
        $personaFile = Join-Path $roleDir 'persona.md'
        $meta = $null
        try { $meta = Get-Content (Join-Path $roleDir 'meta.json') -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }

        $directive = "【角色系统】你是 $role。"
        if (Test-Path $personaFile) {
            $directive += "`n" + (Get-Content $personaFile -Raw -Encoding UTF8).Trim()
        }
        $skills = if ($meta -and $meta.skills) { @($meta.skills) } else { @() }
        $skillsText = Get-RoleSkillsText -RoleName $role -Skills $skills
        if ($skillsText) { $directive += "`n`n" + $skillsText }
        $directive += "`n`n请先 Read 知识库 $knowledge。"
        if (Test-Path $inherit) {
            $directive += "`n本次继承自其他会话，先 Read $inherit。"
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($inheritPath) -and (Test-Path $inheritPath)) {
        if ($directive) { $directive += "`n`n" }
        $directive += "【继承会话】本次会话继承自其他会话，请先 Read $inheritPath。"
    }
    if ($directive) { Write-Output $directive }
} catch {
    # 任何异常都不影响会话启动
}
exit 0
