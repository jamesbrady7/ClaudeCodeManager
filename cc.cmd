@echo off
setlocal EnableDelayedExpansion

rem ---- 禁用 Claude Code 自动更新（防更新下载损坏 exe 导致
rem      "not compatible with Windows" 报错；手动更新可临时删掉这两行）----
set DISABLE_AUTOUPDATER=1
set DISABLE_UPDATES=1

rem ---- 解析会话级供应商/模型：cc ... --provider <name> [--model <name>] ----
set "CC_PROVIDER="
set "CC_PROVIDER_ARG="
set "CC_MODEL="
set "CC_MODEL_ARG="
for %%a in (%*) do (
    if defined CC_PROVIDER_ARG (
        set "CC_PROVIDER=%%a"
        set "CC_PROVIDER_ARG="
    )
    if defined CC_MODEL_ARG (
        set "CC_MODEL=%%a"
        set "CC_MODEL_ARG="
    )
    if /I "%%a"=="--provider" set "CC_PROVIDER_ARG=1"
    if /I "%%a"=="--model" set "CC_MODEL_ARG=1"
)
rem 空 provider 时不传 -Provider（否则 PowerShell 报 MissingArgument）
if defined CC_PROVIDER ( set "CC_PROVIDER_ARGS=-Provider !CC_PROVIDER!" ) else ( set "CC_PROVIDER_ARGS=" )
if defined CC_MODEL ( set "CC_MODEL_ARGS=-Model !CC_MODEL!" ) else ( set "CC_MODEL_ARGS=" )

rem ============================================================
rem  Claude Code Launcher
rem  Config file : %~dp0cc-config.json
rem  Read script : %~dp0cc-config-read.ps1
rem
rem  Usage:
rem    cc                      Start Claude Code (current provider)
rem    cc danger               Danger mode (skip permission prompts)
rem    cc provider             List providers + current model mapping
rem    cc provider switch <n>  Switch to provider <n>
rem    cc mode                 Same as "cc provider"
rem    cc hist                 List past sessions
rem    cc clear [id|all]       Delete sessions
rem    cc resume [id]          Resume a session
rem    cc ui                   Desktop UI (Qt): view / create / resume / bulk-delete
rem    cc backup [days]        Backup sessions (archive retention days, default 365)
rem    cc role <name>          Start a session with a role (persona + knowledge)
rem    cc roles                List roles
rem    cc -p "prompt"          One-shot question
rem    cc help                 Show this help
rem ============================================================

if /I "%1"=="help"    goto help
if /I "%1"=="--help"  goto help
if /I "%1"=="-h"      goto help
if /I "%1"=="danger"  goto danger
if /I "%1"=="provider" goto provider
if /I "%1"=="providers" goto provider
if /I "%1"=="mode"    goto mode
if /I "%1"=="hist"    goto hist
if /I "%1"=="history" goto hist
if /I "%1"=="clear"   goto clear
if /I "%1"=="rm"      goto clear
if /I "%1"=="resume"  goto resume
if /I "%1"=="ui"      goto ui
if /I "%1"=="sessions" goto ui
if /I "%1"=="backup"  goto backup
if /I "%1"=="role"    goto role
if /I "%1"=="roles"   goto role

rem ---- default: normal start with current provider ----
for /f "tokens=1,* delims=|" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cc-config-read.ps1" !CC_PROVIDER_ARGS! !CC_MODEL_ARGS!') do (
    set "%%A=%%B"
)

if "%1"=="" (
    echo [cc] Provider=!CC_CURRENT_PROVIDER!  Model=!ANTHROPIC_MODEL!
    claude
    goto end
)
if /I "%1"=="-p" (
    echo [cc] Provider=!CC_CURRENT_PROVIDER!  Model=!ANTHROPIC_MODEL!
    claude %*
    goto end
)
rem cc --provider <name>：用指定 provider 启动新会话（--provider 已在顶部解析）
if /I "%1"=="--provider" (
    echo [cc] Provider=!CC_CURRENT_PROVIDER!  Model=!ANTHROPIC_MODEL!
    claude
    goto end
)
claude %*
goto end

:danger
for /f "tokens=1,* delims=|" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cc-config-read.ps1" !CC_PROVIDER_ARGS! !CC_MODEL_ARGS!') do (
    set "%%A=%%B"
)
rem 支持 danger 模式恢复会话（保留原上下文）
if /I "%2"=="--resume" (
    echo [cc] Danger mode resume  Provider=!CC_CURRENT_PROVIDER!  Model=!ANTHROPIC_MODEL!
    claude --dangerously-skip-permissions --resume %3
    goto end
)
echo [cc] Danger mode  Provider=!CC_CURRENT_PROVIDER!  Model=!ANTHROPIC_MODEL!
claude --dangerously-skip-permissions
goto end

:provider
chcp 65001 >nul
if /I "%2"=="switch" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cc-provider.ps1" -Action switch -Target %3
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cc-provider.ps1" -Action list
)
goto end

:mode
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cc-provider.ps1" -Action list
goto end

:hist
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cc-history.ps1"
goto end

:clear
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cc-clear.ps1" %2
goto end

:resume
for /f "tokens=1,* delims=|" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cc-config-read.ps1" !CC_PROVIDER_ARGS! !CC_MODEL_ARGS!') do (
    set "%%A=%%B"
)
if "%2"=="" (
  claude --resume
) else (
  claude --resume %2
)
goto end

:ui
chcp 65001 >nul
rem 启动 Qt 桌面应用（pythonw 无控制台；若 pythonw 不在 PATH 改用 python）
if exist "%~dp0cc-ui.exe" (start "" "%~dp0cc-ui.exe") else (start "" pythonw.exe "%~dp0cc-ui-qt.py")
goto end

:backup
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cc-backup.ps1" %2
goto end

:role
for /f "tokens=1,* delims=|" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cc-config-read.ps1" !CC_PROVIDER_ARGS! !CC_MODEL_ARGS!') do (
    set "%%A=%%B"
)
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cc-role.ps1" %*
goto end

:help
echo.
echo Claude Code Launcher
echo ====================
echo   Config: %~dp0cc-config.json
echo.
echo   cc                      Start (default provider, normal permissions)
echo   cc danger               Danger mode (skip permission prompts)
echo   cc provider             List providers + model mapping
echo   cc provider switch ^<n^>  Switch provider (one field change)
echo   cc mode                 Same as "cc provider"
echo   cc hist                 List past sessions
echo   cc clear [id^|all]       Delete sessions
echo   cc resume [id]          Resume a session
echo   cc ui                   Desktop UI (Qt): view / create / resume / bulk-delete
echo   cc backup [days]        Backup sessions (archive retention days, default 365)
echo   cc role ^<name^>        Start a session with a role (persona + knowledge)
echo   cc role ^<name^> --from Start with inheritance from other sessions
echo   cc roles                List roles
echo   cc -p "prompt"          One-shot question
echo.
echo   To configure providers, edit:
echo     %~dp0cc-config.json
echo.
goto end

:end
endlocal