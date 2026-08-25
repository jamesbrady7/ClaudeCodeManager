# Manage providers and show current model mapping
# Usage:
#   cc provider            -> list providers + current model mapping
#   cc provider list       -> same as above
#   cc provider switch <name>  -> switch current provider to <name>
#   cc mode                -> alias for "provider list" (kept for compatibility)

param(
    [string]$Action = "list",
    [string]$Target = ""
)

$ErrorActionPreference = 'Stop'
$configDir = $env:CLAUDE_CONFIG_DIR
if (-not $configDir) { $configDir = 'D:\ClaudeCode' }
$cfgPath = Join-Path $configDir 'cc-config.json'

function Read-Config {
    $raw = Get-Content $cfgPath -Raw -Encoding UTF8
    $cfg = $raw | ConvertFrom-Json
    return @{ Raw = $raw; Cfg = $cfg }
}

switch ($Action.ToLower()) {
    "list" {
        $r = Read-Config
        $providers = $r.Cfg.'provider config'
        $default = $providers.'default provider'
        $names = @($providers.PSObject.Properties.Name | Where-Object { $_ -ne 'default provider' })

        Write-Host ""
        Write-Host "=== Providers ===" -ForegroundColor Cyan
        foreach ($n in $names) {
            $mark = if ($n -eq $default) { "  [default]" } else { "" }
            Write-Host ("  {0}{1}" -f $n, $mark)
        }
        Write-Host ""
        Write-Host ("Default provider: " + $default) -ForegroundColor Yellow

        # show default provider's model mapping
        $slot = $providers.$default
        if ($slot) {
            Write-Host ""
            Write-Host "Model mapping (default provider):" -ForegroundColor Cyan
            Write-Host ("  baseUrl : " + $slot.baseUrl) -ForegroundColor DarkGray
            Write-Host ("  model   : " + $slot.model) -ForegroundColor White
            if ($slot.fastModel) {
                Write-Host ("  fast    : " + $slot.fastModel) -ForegroundColor White
            } else {
                Write-Host ("  fast    : (not set, falls back to model)") -ForegroundColor DarkGray
            }
        }
        Write-Host ""
        Write-Host "Set default:  cc provider switch <name>" -ForegroundColor Gray
        Write-Host "Per-session:  cc resume <id> --provider <name>" -ForegroundColor Gray
        Write-Host ""
    }

    "switch" {
        if (-not $Target) {
            Write-Host "Usage: cc provider switch <name>" -ForegroundColor Red
            Write-Host "Run 'cc provider' to see available providers." -ForegroundColor Gray
            exit 1
        }
        $r = Read-Config
        $providers = $r.Cfg.'provider config'
        $names = @($providers.PSObject.Properties.Name | Where-Object { $_ -ne 'default provider' })

        if ($names -notcontains $Target) {
            Write-Host "Provider '$Target' not found. Available: $($names -join ', ')" -ForegroundColor Red
            exit 1
        }

        # Preserve formatting: replace only the "default provider" value
        $newRaw = [regex]::Replace($r.Raw, '("default provider"\s*:\s*)"[^"]*"', ('${1}"' + $Target + '"'))
        $null = $newRaw | ConvertFrom-Json  # validate
        [System.IO.File]::WriteAllText($cfgPath, $newRaw, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host ("Default provider 已设为: " + $Target) -ForegroundColor Green
        Write-Host "新会话默认用这个 provider；会话级用 cc resume <id> --provider <name>。" -ForegroundColor Gray
    }

    default {
        Write-Host "Unknown action: $Action" -ForegroundColor Red
        Write-Host "Usage: cc provider [list|switch <name>]" -ForegroundColor Gray
        exit 1
    }
}