# ============================================================
#  cc-role.ps1  —  角色系统启动器 + 会话继承提取
#
#  用法:
#    cc roles                      列出所有角色
#    cc role new <name> ["描述"]   新建角色
#    cc role rm <name>             删除角色
#    cc role <name>                以某角色启动会话
#    cc role <name> --from <ids>   启动并继承指定会话（ids 逗号分隔）
#    cc role <name> --extract <ids> 只生成 inherit.md 不启动（验证用）
#
#  角色 = roles\<name>\persona.md（人设）+ knowledge.md（长期知识库）
#  启动时把 persona 用 --agents <json> 内联注入（不依赖 agent 文件
#  发现，对第三方模型也可靠），CC_ROLE 环境变量供 SessionStart hook
#  输出读取知识库指令到会话上下文。
# ============================================================

$ErrorActionPreference = 'Stop'

$configDir = $env:CLAUDE_CONFIG_DIR
if (-not $configDir) { $configDir = 'D:\ClaudeCode' }
$rolesDir    = Join-Path $configDir 'roles'
$projectsDir = Join-Path $configDir 'projects'
$skillsDir   = Join-Path $configDir 'skills'

$nameRe    = '^[a-zA-Z0-9_-]+$'
$reserved  = @('new','list','ls','help','rm','roles','role')
$INHERIT_MAX_BLOCKS = 60
$INHERIT_MAX_CHAR   = 800
$INHERIT_BUDGET     = 30000

# 可被环境变量覆盖的 claude 命令（默认走 PATH 上的 claude shim）
$claudeCmd = if ($env:CC_CLAUDE_BIN) { $env:CC_CLAUDE_BIN } else { 'claude' }

function Show-Usage {
    Write-Host ""
    Write-Host "角色系统用法:" -ForegroundColor Cyan
    Write-Host "  cc roles                      列出所有角色"
    Write-Host "  cc role new <name> [描述]     新建角色"
    Write-Host "  cc role rm <name>             删除角色"
    Write-Host "  cc role <name>                以该角色启动会话"
    Write-Host "  cc role <name> --from <ids>   启动并继承指定会话（ids 逗号分隔）"
    Write-Host "  cc role <name> --extract <ids> 只生成继承要点，不启动（验证用）"
    Write-Host ""
}

function Test-RoleName([string]$name) {
    if (-not $name) { return $false }
    if ($name -notmatch $nameRe) { return $false }
    if ($reserved -contains $name) { return $false }
    return $true
}

function Get-MetaPath([string]$name) { Join-Path (Join-Path $rolesDir $name) 'meta.json' }

function Get-RoleMeta([string]$name) {
    $p = Get-MetaPath $name
    if (Test-Path $p) {
        try { return (Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
    }
    return $null
}

# 返回第一个匹配的 transcript 路径；找不到返回 $null
function Locate-Transcript([string]$id) {
    if ($id -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') { return $null }
    if (-not (Test-Path $projectsDir)) { return $null }
    foreach ($d in (Get-ChildItem -Path $projectsDir -Directory -ErrorAction SilentlyContinue)) {
        if ($d.Name -eq 'memory') { continue }
        $p = Join-Path $d.FullName "$id.jsonl"
        if (Test-Path $p) { return $p }
    }
    return $null
}

# 从 message.content（字符串或块数组）取第一个 text 文本
function Get-TextContent($content) {
    if ($null -eq $content) { return '' }
    if ($content -is [string]) { return $content }
    if ($content -is [System.Array]) {
        foreach ($blk in $content) {
            if ($blk.type -eq 'text' -and $blk.text) { return [string]$blk.text }
        }
    }
    return ''
}

function Trunc([string]$s, [int]$n) {
    if ($s.Length -le $n) { return $s }
    return $s.Substring(0, $n) + '…'
}

function Write-Inherit {
    param([string]$RoleDir, [string[]]$Ids)
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine("# 继承自 $($Ids.Count) 个会话")
    [void]$sb.AppendLine("生成时间: " + (Get-Date).ToUniversalTime().ToString('o'))
    [void]$sb.AppendLine("")

    foreach ($id in $Ids) {
        $transcript = Locate-Transcript $id
        if (-not $transcript) {
            [void]$sb.AppendLine("")
            [void]$sb.AppendLine("## 会话 $id — 未找到记录")
            continue
        }
        $queue = New-Object 'System.Collections.Generic.Queue[string]'
        $title = ''; $cwd = ''; $firstTs = ''
        foreach ($line in [System.IO.File]::ReadLines($transcript, [System.Text.Encoding]::UTF8)) {
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            $o = $null
            try { $o = $line | ConvertFrom-Json } catch { continue }
            if ($null -eq $o) { continue }
            if (-not $firstTs -and $o.timestamp) { $firstTs = $o.timestamp }
            if ($o.type -eq 'user') {
                if (-not $title) {
                    $title = Trunc (Get-TextContent $o.message.content) 80
                    $cwd = $o.cwd
                }
                $t = Get-TextContent $o.message.content
                if ($t) { $queue.Enqueue(('用户: ' + (Trunc $t $INHERIT_MAX_CHAR))) }
            } elseif ($o.type -eq 'assistant') {
                $blocks = $o.message.content
                if ($blocks -is [System.Array]) {
                    foreach ($blk in $blocks) {
                        if ($blk.type -eq 'text' -and $blk.text) {
                            $queue.Enqueue(('助手: ' + (Trunc ([string]$blk.text) $INHERIT_MAX_CHAR)))
                        }
                    }
                }
            }
            while ($queue.Count -gt $INHERIT_MAX_BLOCKS) { [void]$queue.Dequeue() }
        }
        [void]$sb.AppendLine("")
        [void]$sb.AppendLine("## 会话 $id")
        [void]$sb.AppendLine("标题: $title")
        if ($cwd)   { [void]$sb.AppendLine("目录: $cwd") }
        if ($firstTs){ [void]$sb.AppendLine("开始: $firstTs") }
        [void]$sb.AppendLine("")
        if ($queue.Count -eq 0) {
            [void]$sb.AppendLine("（无可提取的问答文本）")
        } else {
            [void]$sb.AppendLine(($queue -join "`n"))
        }
        if ($sb.Length -ge $INHERIT_BUDGET) { break }
    }

    [System.IO.File]::WriteAllText(
        (Join-Path $RoleDir 'inherit.md'),
        $sb.ToString(),
        (New-Object System.Text.UTF8Encoding($false)))
    Write-Host ("inherit.md 已生成: " + (Join-Path $RoleDir 'inherit.md') + "（" + $sb.Length + " 字符）") -ForegroundColor Cyan
}

function New-Role {
    param([string]$Name, [string]$Description)
    if (-not (Test-RoleName $Name)) {
        Write-Host "非法角色名 '$Name'（须为字母/数字/_/-，且不能是保留名）" -ForegroundColor Red
        exit 1
    }
    $roleDir = Join-Path $rolesDir $Name
    if (Test-Path $roleDir) {
        Write-Host "角色 '$Name' 已存在" -ForegroundColor Yellow
        exit 1
    }
    if (-not (Test-Path $rolesDir)) { New-Item -ItemType Directory -Force -Path $rolesDir | Out-Null }
    New-Item -ItemType Directory -Force -Path $roleDir | Out-Null

    if ([string]::IsNullOrWhiteSpace($Description)) { $Description = "角色 $Name" }

    $meta = @{
        name        = $Name
        description = $Description
        created     = (Get-Date).ToUniversalTime().ToString('o')
    }
    [System.IO.File]::WriteAllText((Get-MetaPath $Name), ($meta | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))

    $personaTemplate = @'
# 角色：@NAME@

@DESC@

你是 @NAME@，一个拥有长期记忆的资深专家。你的知识库文件是：
D:\ClaudeCode\roles\@NAME@\knowledge.md

## 会话开始
每次会话开始时，第一步用 Read 阅读知识库 D:\ClaudeCode\roles\@NAME@\knowledge.md。
若存在 D:\ClaudeCode\roles\@NAME@\inherit.md，一并阅读它（那是本次继承的要点）。
不要复述知识库内容，直接运用。

## 自动学习（重要）
学到**重要且可复用**的知识时，立即用 Write 或 Edit 写回知识库。
判断标准：下次遇到同类问题还会用到的才算重要，包括：
- 关键结论与决策（以及原因）
- 项目/代码的约定与结构
- 常用 API、命令、配置项用法
- 踩过的坑与规避方法
- 可复用的模式与流程

## 知识库格式
- 用「## 主题」分节，每节 3-6 行精炼要点，中文书写
- 主题已存在则用 Edit 更新，不新建重复小节
- 删除/精简过时内容
- 不记录：临时过程、无关闲聊、大段代码全文

## 会话结束
会话末尾回顾本次工作，如有值得沉淀的知识，先更新知识库再结束。

现在，请先 Read 知识库文件，然后等待任务。
'@
    $persona = $personaTemplate.Replace('@NAME@', $Name).Replace('@DESC@', $Description)
    [System.IO.File]::WriteAllText((Join-Path $roleDir 'persona.md'), $persona, (New-Object System.Text.UTF8Encoding($false)))

    $knowledgeTemplate = @'
# 知识库：@NAME@

> 本文件是本角色的长期记忆，随会话自动积累。
> 由角色在会话中学到重要知识后用 Write/Edit 维护。

## 维护规范
- 用「## 主题」分节，每节 3-6 行精炼要点，中文书写
- 同主题用 Edit 更新，不新建重复小节；删除/精简过时内容
- 记录：关键结论、约定、API、命令、坑、可复用模式
- 不记录：过程、闲聊、大段代码全文
- 知识库应保持精炼；若超过约 30KB / 600 行，请主动合并精简

## 开始
（此处随会话积累）
'@
    $knowledge = $knowledgeTemplate.Replace('@NAME@', $Name)
    [System.IO.File]::WriteAllText((Join-Path $roleDir 'knowledge.md'), $knowledge, (New-Object System.Text.UTF8Encoding($false)))

    Write-Host "角色 '$Name' 已创建" -ForegroundColor Green
    Write-Host ("  人设  : " + (Join-Path $roleDir 'persona.md'))
    Write-Host ("  知识库: " + (Join-Path $roleDir 'knowledge.md'))
    Write-Host "启动: cc role $Name"
}

function Remove-Role {
    param([string]$Name)
    if (-not (Test-RoleName $Name)) {
        Write-Host "非法角色名 '$Name'" -ForegroundColor Red
        exit 1
    }
    $roleDir = Join-Path $rolesDir $Name
    if (Test-Path $roleDir) { Remove-Item $roleDir -Recurse -Force }
    Write-Host "角色 '$Name' 已删除" -ForegroundColor Green
}

function List-Roles {
    if (-not (Test-Path $rolesDir)) {
        Write-Host "还没有角色。用 'cc role new <name> [描述]' 创建。" -ForegroundColor Yellow
        return
    }
    $roles = Get-ChildItem -Path $rolesDir -Directory | Where-Object { $_.Name -match $nameRe }
    if (-not $roles) { Write-Host "还没有角色。" -ForegroundColor Yellow; return }
    Write-Host ""
    Write-Host "=== 角色列表 ===" -ForegroundColor Cyan
    foreach ($r in $roles) {
        $meta = Get-RoleMeta $r.Name
        $desc = if ($meta -and $meta.description) { $meta.description } else { '(无描述)' }
        $k = Join-Path $r.FullName 'knowledge.md'
        $s = Join-Path $r.FullName 'sessions.jsonl'
        $kSize = if (Test-Path $k) { [math]::Round((Get-Item $k).Length / 1KB, 1) } else { 0 }
        $sCount = if (Test-Path $s) { @(Get-Content $s -ErrorAction SilentlyContinue | Where-Object { $_.Trim() }).Count } else { 0 }
        Write-Host ("  {0}  —  {1}" -f $r.Name, $desc) -ForegroundColor White
        Write-Host ("      知识库 {0} KB · {1} 个会话" -f $kSize, $sCount) -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Host "启动: cc role <name>   /   cc role <name> --from <ids>" -ForegroundColor Gray
}

function Start-Role {
    param([string]$Name, [string]$FromIds, [switch]$ExtractOnly)
    if (-not (Test-RoleName $Name)) {
        Write-Host "非法角色名 '$Name'" -ForegroundColor Red
        exit 1
    }
    $roleDir = Join-Path $rolesDir $Name
    if (-not (Test-Path $roleDir)) {
        Write-Host "角色 '$Name' 不存在。先用 'cc role new $Name' 创建。" -ForegroundColor Red
        exit 1
    }
    $personaFile = Join-Path $roleDir 'persona.md'
    if (-not (Test-Path $personaFile)) {
        Write-Host "缺少人设文件 $personaFile，无法启动。请重新创建角色。" -ForegroundColor Red
        exit 1
    }

    if ($FromIds) {
        Write-Inherit -RoleDir $roleDir -Ids ($FromIds.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    } else {
        Remove-Item (Join-Path $roleDir 'inherit.md') -Force -ErrorAction SilentlyContinue
    }

    if ($ExtractOnly) { return }

    # 人设/技能由 SessionStart hook（track-session.ps1）注入会话上下文。
    # 这里只设 CC_ROLE 并启动普通 claude（交互模式下 --agent 需要真实
    # agent 文件，内联 --agents 不被认可，故改走 hook 通道）。
    $env:CC_ROLE = $Name
    Write-Host ("启动角色会话: $Name（CC_ROLE=" + $Name + "）") -ForegroundColor Green
    & $claudeCmd
    $code = $LASTEXITCODE
    Remove-Item Env:CC_ROLE -ErrorAction SilentlyContinue
    exit $code
}

# ---------------- 主流程 ----------------
if ($args.Count -eq 0) { Show-Usage; exit 0 }
$cmd = $args[0]
switch ($cmd) {
    'roles' { List-Roles }
    'role' {
        if ($args.Count -lt 2) { Show-Usage; exit 0 }
        $sub = $args[1]
        if ($sub -eq 'new') {
            if ($args.Count -lt 3) { Write-Host "用法: cc role new <name> [描述]" -ForegroundColor Yellow; exit 1 }
            $desc = if ($args.Count -ge 4) { $args[3] } else { '' }
            New-Role -Name $args[2] -Description $desc
        } elseif ($sub -eq 'rm') {
            if ($args.Count -lt 3) { Write-Host "用法: cc role rm <name>" -ForegroundColor Yellow; exit 1 }
            Remove-Role $args[2]
        } elseif ($sub -eq 'help') {
            Show-Usage
        } else {
            $name = $sub
            $fromIds = ''
            $extractOnly = $false
            for ($i = 2; $i -lt $args.Count; $i++) {
                if (($args[$i] -eq '--from' -or $args[$i] -eq '--extract') -and ($i + 1) -lt $args.Count) {
                    $fromIds = $args[$i + 1]
                    if ($args[$i] -eq '--extract') { $extractOnly = $true }
                    $i++
                }
            }
            Start-Role -Name $name -FromIds $fromIds -ExtractOnly:$extractOnly
        }
    }
    default { Show-Usage }
}
