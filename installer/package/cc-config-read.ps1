# Reads cc-config.json and emits "KEY|VALUE" lines for cc.cmd to consume.
# Config structure:
#   "provider config": {
#     "current provider": "deepseek",
#     "deepseek": { baseUrl, apiKey, model, fastModel? },
#     "glm":      { baseUrl, apiKey, model, fastModel? },
#     ...
#   }
#
# fastModel is OPTIONAL. It controls the cheaper model used for background
# jobs (session titles, subagents, context collapse). It must belong to the
# SAME provider as the main model.
#
# Defensive rule: if fastModel is absent/empty/invalid, fall back to main model.

param(
    [string]$Provider = ""   # 会话级指定 provider；为空则用 default provider
)

$ErrorActionPreference = 'Stop'
$configDir = $env:CLAUDE_CONFIG_DIR
if (-not $configDir) { $configDir = 'D:\ClaudeCode' }
$cfgPath = Join-Path $configDir 'cc-config.json'

try {
    $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-Output "CONFIG_ERROR|Failed to parse cc-config.json: $_"
    exit 1
}

$providers = $cfg.'provider config'
if (-not $providers) {
    Write-Output "CONFIG_ERROR|Missing 'provider config' section"
    exit 1
}

$current = if ($Provider) { $Provider } else { $providers.'default provider' }
if ([string]::IsNullOrWhiteSpace($current)) {
    Write-Output "CONFIG_ERROR|Missing 'default provider'"
    exit 1
}

$slot = $providers.$current
if (-not $slot) {
    Write-Output "CONFIG_ERROR|Provider not found: $current"
    exit 1
}

$mainModel = $slot.model
if ([string]::IsNullOrWhiteSpace($mainModel)) {
    Write-Output "CONFIG_ERROR|Missing 'model' for provider '$current'"
    exit 1
}
$mainModel = $mainModel.Trim()

# ---- Validate fastModel ----
function Test-ValidModelName([string]$name) {
    if ([string]::IsNullOrWhiteSpace($name)) { return $false }
    $t = $name.Trim()
    if ($t -match '://') { return $false }
    if ($t -match '^(sk-|sk_|gsk_|AKIA|AIza)') { return $false }
    if ($t -match '\s') { return $false }
    if ($t -match '[/\\]') { return $false }
    return $true
}

$fastModel = $mainModel
if (Test-ValidModelName $slot.fastModel) {
    $fastModel = $slot.fastModel.Trim()
}

# ---- 认证变量：按 claude 版本只设一个（新版认 AUTH_TOKEN 的 Bearer，老版 0.x 只认 API_KEY）----
# 两个都设会触发新版 claude "auth conflict" 警告且行为不可预期，必须二选一。
$authName = 'ANTHROPIC_AUTH_TOKEN'
try {
    $verLine = (& claude --version 2>$null) -join ' '
    if ($verLine -match '^\s*(\d+)\.(\d+)') {
        if ([int]$Matches[1] -lt 1) { $authName = 'ANTHROPIC_API_KEY' }  # 0.x 老版
    }
} catch { }   # claude 不在 PATH 时默认新版（AUTH_TOKEN）

Write-Output "ANTHROPIC_BASE_URL|$($slot.baseUrl)"
Write-Output "$authName|$($slot.apiKey)"
Write-Output "ANTHROPIC_MODEL|$mainModel"
Write-Output "ANTHROPIC_SMALL_FAST_MODEL|$fastModel"
Write-Output "CLAUDE_CODE_SUBAGENT_MODEL|$fastModel"
Write-Output "CLAUDE_CONTEXT_COLLAPSE_MODEL|$fastModel"
Write-Output "CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT|1"
Write-Output "CLAUDE_CONFIG_DIR|$configDir"
Write-Output "CC_CURRENT_PROVIDER|$current"