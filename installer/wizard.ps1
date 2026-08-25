# ============================================================
#  ClaudeCodeManager 图形安装向导
#    · 可选安装目录（默认 %LOCALAPPDATA%\ClaudeCodeManager）
#    · 可选 cc-config.json（用户的 provider 配置，含 API 密钥）
#    · 检测已有安装 → 提示可先卸载旧版
#    · 确定后调用 setup.ps1 执行安装
# ============================================================
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$setupScript = Join-Path $PSScriptRoot 'setup.ps1'


function Test-ExistingInstall([string]$path) {
    # 已安装判定：有冻结 app（cc-ui.exe）或有启动器（cc.cmd + cc-role.ps1）都算
    if (-not (Test-Path $path)) { return $false }
    if (Test-Path (Join-Path $path 'cc-ui.exe')) { return $true }
    if ((Test-Path (Join-Path $path 'cc.cmd')) -and (Test-Path (Join-Path $path 'cc-role.ps1'))) {
        return $true
    }
    return $false
}


function Find-Installs([string]$except) {
    # 扫描常见安装位置 + 所有盘符根目录下的 ClaudeCodeManager/ClaudeCode（覆盖任意位置），
    # 返回除 except 外的已安装目录列表。
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'ClaudeCodeManager'),
        (Join-Path $env:LOCALAPPDATA 'ClaudeCodeManager\cc-ui'),
        (Join-Path ${env:ProgramFiles} 'ClaudeCodeManager'),
        (Join-Path ${env:ProgramFiles(x86)} 'ClaudeCodeManager')
    )
    foreach ($drv in (Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
        $root = $drv.Root.TrimEnd('\')
        if ($root) {
            $candidates += (Join-Path $root 'ClaudeCodeManager')
            $candidates += (Join-Path $root 'ClaudeCode')
        }
    }
    $found = @()
    foreach ($c in ($candidates | Select-Object -Unique)) {
        if ($c -and $c -ne $except -and (Test-ExistingInstall $c)) { $found += $c }
    }
    return $found
}


function Remove-Install([string]$path) {
    # 删桌面快捷方式
    $desktop = [Environment]::GetFolderPath('Desktop')
    $lnk = Join-Path $desktop 'Claude Code 管理.lnk'
    if (Test-Path $lnk) { Remove-Item $lnk -Force }
    # 清 CLAUDE_CONFIG_DIR（若指向该目录）
    $ccd = [Environment]::GetEnvironmentVariable('CLAUDE_CONFIG_DIR', 'User')
    if ($ccd -and $ccd -ieq $path) {
        [Environment]::SetEnvironmentVariable('CLAUDE_CONFIG_DIR', $null, 'User')
    }
    # 从用户 PATH 移除
    $up = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($up -like "*$path*") {
        $new = ($up -split ';' | Where-Object { $_ -notlike "*$path*" }) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $new, 'User')
    }
    # 删目录
    if (Test-Path $path) { Remove-Item $path -Recurse -Force }
}


function Show-Wizard {
    # ---- 布局常量（按窗体宽度计算，缩放不挤；全部预计算，避免 New-Object 内表达式歧义）----
    $W = 660; $H = 450; $M = 16
    $fieldW = $W - $M * 2 - 8 - 120     # 文本框宽
    $btnBrowseX = $M + $fieldW + 8      # 浏览按钮 x
    $statusW = $W - $M * 2              # 标签宽
    $btnY = $H - 56                     # 按钮行 y
    $btnInstallX = $W - $M - 312
    $btnUninstallX = $W - $M - 208
    $btnCancelX = $W - $M - 104

    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'Claude Code 管理器 · 安装'
    $form.ClientSize = New-Object System.Drawing.Size($W, $H)
    $form.StartPosition = 'CenterScreen'
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.Font = New-Object System.Drawing.Font('Segoe UI', 9)

    # ---- 标题 ----
    $title = New-Object System.Windows.Forms.Label
    $title.Text = 'Claude Code 管理器'
    $title.Font = New-Object System.Drawing.Font('Segoe UI', 14, [System.Drawing.FontStyle]::Bold)
    $title.Location = New-Object System.Drawing.Point($M, 16)
    $title.AutoSize = $true
    $form.Controls.Add($title)
    $sub = New-Object System.Windows.Forms.Label
    $sub.Text = '安装桌面应用 + 启动器配置，自动检测 Claude Code。'
    $sub.ForeColor = [System.Drawing.Color]::Gray
    $sub.Location = New-Object System.Drawing.Point($M, 46)
    $sub.AutoSize = $true
    $form.Controls.Add($sub)

    # ---- 安装目录 ----
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = '安装目录（也是数据/配置存放处）：'
    $lbl.Location = New-Object System.Drawing.Point($M, 80); $lbl.AutoSize = $true
    $form.Controls.Add($lbl)
    $txtPath = New-Object System.Windows.Forms.TextBox
    $txtPath.Location = New-Object System.Drawing.Point($M, 104)
    $txtPath.Size = New-Object System.Drawing.Size($fieldW, 26)
    $form.Controls.Add($txtPath)
    $btnBrowse = New-Object System.Windows.Forms.Button
    $btnBrowse.Text = '浏览…'
    $btnBrowse.Location = New-Object System.Drawing.Point($btnBrowseX, 103)
    $btnBrowse.Size = New-Object System.Drawing.Size(120, 28)
    $btnBrowse.Add_Click({ $d = New-Object System.Windows.Forms.FolderBrowserDialog; if ($d.ShowDialog() -eq 'OK') { $txtPath.Text = $d.SelectedPath; Update-Status } })
    $form.Controls.Add($btnBrowse)

    # ---- cc-config.json（可选）----
    $lbl2 = New-Object System.Windows.Forms.Label
    $lbl2.Text = 'cc-config.json（可选：你的 provider 配置，含 API 密钥）：'
    $lbl2.Location = New-Object System.Drawing.Point($M, 148); $lbl2.AutoSize = $true
    $form.Controls.Add($lbl2)
    $txtCfg = New-Object System.Windows.Forms.TextBox
    $txtCfg.Location = New-Object System.Drawing.Point($M, 172)
    $txtCfg.Size = New-Object System.Drawing.Size($fieldW, 26)
    $form.Controls.Add($txtCfg)
    $btnCfg = New-Object System.Windows.Forms.Button
    $btnCfg.Text = '浏览…'
    $btnCfg.Location = New-Object System.Drawing.Point($btnBrowseX, 171)
    $btnCfg.Size = New-Object System.Drawing.Size(120, 28)
    $btnCfg.Add_Click({ $d = New-Object System.Windows.Forms.OpenFileDialog; $d.Filter = 'JSON|*.json'; if ($d.ShowDialog() -eq 'OK') { $txtCfg.Text = $d.FileName } })
    $form.Controls.Add($btnCfg)

    # ---- 状态提示（所选路径的检测）----
    $lblStatus = New-Object System.Windows.Forms.Label
    $lblStatus.Location = New-Object System.Drawing.Point($M, 220)
    $lblStatus.Size = New-Object System.Drawing.Size($statusW, 34)
    $lblStatus.AutoEllipsis = $true
    $form.Controls.Add($lblStatus)

    # ---- 其他位置的旧安装提示 + 自动卸载 ----
    $lblOthers = New-Object System.Windows.Forms.Label
    $lblOthers.Location = New-Object System.Drawing.Point($M, 256)
    $lblOthers.Size = New-Object System.Drawing.Size($statusW, 30)
    $lblOthers.ForeColor = [System.Drawing.Color]::Firebrick
    $lblOthers.AutoEllipsis = $true
    $form.Controls.Add($lblOthers)
    $chkAutoUninstall = New-Object System.Windows.Forms.CheckBox
    $chkAutoUninstall.Text = '安装前自动卸载检测到的旧安装（默认不勾选：避免误删含 .git 的开发目录）'
    $chkAutoUninstall.Location = New-Object System.Drawing.Point($M, 290)
    $chkAutoUninstall.AutoSize = $true
    $chkAutoUninstall.Checked = $false
    $form.Controls.Add($chkAutoUninstall)

    # ---- 按钮（右下角标准布局）----
    $btnInstall = New-Object System.Windows.Forms.Button
    $btnInstall.Text = '安装'; $btnInstall.Size = New-Object System.Drawing.Size(100, 32)
    $btnInstall.Location = New-Object System.Drawing.Point($btnInstallX, $btnY)
    $btnInstall.Anchor = 'Bottom,Right'
    $form.Controls.Add($btnInstall)
    $btnUninstall = New-Object System.Windows.Forms.Button
    $btnUninstall.Text = '卸载旧版'; $btnUninstall.Size = New-Object System.Drawing.Size(100, 32)
    $btnUninstall.Location = New-Object System.Drawing.Point($btnUninstallX, $btnY)
    $btnUninstall.Anchor = 'Bottom,Right'
    $btnUninstall.Enabled = $false
    $form.Controls.Add($btnUninstall)
    $btnCancel = New-Object System.Windows.Forms.Button
    $btnCancel.Text = '取消'; $btnCancel.Size = New-Object System.Drawing.Size(100, 32)
    $btnCancel.Location = New-Object System.Drawing.Point($btnCancelX, $btnY)
    $btnCancel.Anchor = 'Bottom,Right'
    $form.Controls.Add($btnCancel)

    # ---- 智能默认路径：检测已知安装（LocalAppData 或 D:\ClaudeCode）----
    $known = @((Join-Path $env:LOCALAPPDATA 'ClaudeCodeManager'), 'D:\ClaudeCode')
    $found = $known | Where-Object { Test-ExistingInstall $_ } | Select-Object -First 1
    if ($found) { $txtPath.Text = $found } else { $txtPath.Text = $known[0] }

    function Update-Status {
        $p = $txtPath.Text.Trim()
        if (Test-ExistingInstall $p) {
            $lblStatus.ForeColor = [System.Drawing.Color]::DarkOrange
            $lblStatus.Text = "检测到所选路径已有安装：$p。点「安装」=覆盖升级（保留数据/密钥）。"
            $btnUninstall.Enabled = $true
        } else {
            $lblStatus.ForeColor = [System.Drawing.Color]::Gray
            $lblStatus.Text = "将全新安装到：$p"
            $btnUninstall.Enabled = $false
        }
        # 扫描其他位置的旧安装
        $others = Find-Installs $p
        if ($others) {
            $lblOthers.Text = ('检测到其他位置的旧安装：' + ($others -join '；'))
            $chkAutoUninstall.Enabled = $true
        } else {
            $lblOthers.Text = ''
            $chkAutoUninstall.Enabled = $false
        }
    }
    $txtPath.Add_TextChanged({ Update-Status })
    Update-Status

    $btnInstall.Add_Click({
        $dest = $txtPath.Text.Trim()
        $cfg = $txtCfg.Text.Trim()
        if (-not $dest) { [System.Windows.Forms.MessageBox]::Show('请选择安装目录', '提示') | Out-Null; return }
        if ($cfg -and -not (Test-Path $cfg)) { [System.Windows.Forms.MessageBox]::Show('cc-config.json 路径无效', '提示') | Out-Null; return }
        # 安装前：若勾选且检测到其他位置的旧安装 → 先卸载它们（避免两套并存冲突）。
        # 二次确认并标注含 .git 的目录（防止误删代码仓库/开发目录）。
        if ($chkAutoUninstall.Checked) {
            $olds = @(Find-Installs $dest)
            if ($olds) {
                $list = ($olds | ForEach-Object {
                    $git = if (Test-Path (Join-Path $_ '.git')) { '（含 .git，删除不可恢复）' } else { '' }
                    "  · $_ $git"
                }) -join "`n"
                $confirm = [System.Windows.Forms.MessageBox]::Show(
                    "将先卸载以下位置的旧安装：`n$list`n`n继续？",
                    '确认卸载旧安装', 'YesNo', 'Warning', 'No')
                if ($confirm -ne 'Yes') { return }
                foreach ($old in $olds) { Remove-Install $old }
            }
        }
        $form.Hide()
        try {
            & $setupScript -Dest $dest -ConfigPath $cfg
            [System.Windows.Forms.MessageBox]::Show('安装完成！桌面已创建「Claude Code 管理」快捷方式。', '完成') | Out-Null
        } catch {
            [System.Windows.Forms.MessageBox]::Show("安装失败：$($_.Exception.Message)", '错误', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
        }
        $form.Close()
    })
    $btnUninstall.Add_Click({
        $dest = $txtPath.Text.Trim()
        if ([System.Windows.Forms.MessageBox]::Show("确定卸载该目录的安装？`n$dest`n`n（将删除该目录及其中的全部数据/配置）", '确认卸载', [System.Windows.Forms.MessageBoxButtons]::YesNo) -eq 'Yes') {
            Remove-Install $dest
            [System.Windows.Forms.MessageBox]::Show('已卸载。', '卸载') | Out-Null
            Update-Status
        }
    })
    $btnCancel.Add_Click({ $form.Close() })

    $form.Add_Shown({ $form.Activate() })
    $form.ShowDialog() | Out-Null
}

Show-Wizard
