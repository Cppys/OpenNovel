# =============================================================================
# OpenNovel AI 写作系统 - Windows 一键安装器
# 依赖：PowerShell 5.1+（Windows 10/11 自带）
# =============================================================================

# --- 强制 UTF-8 ---
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# --- 安装包根目录（install.bat 所在目录）---
$ScriptRoot = Split-Path -Parent $PSScriptRoot   # installer/ 的父目录
if (-not (Test-Path "$ScriptRoot\pyproject.toml")) {
    $ScriptRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}

# --- 辅助函数 ---

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath    = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Write-Log {
    param([string]$Message)
    if ($script:txtLog) {
        $script:txtLog.AppendText("$Message`r`n")
        $script:txtLog.ScrollToCaret()
        [System.Windows.Forms.Application]::DoEvents()
    }
    Write-Host $Message
}

function Set-Progress {
    param([int]$Value)
    if ($script:progressBar) {
        $script:progressBar.Value = [Math]::Min($Value, 100)
        [System.Windows.Forms.Application]::DoEvents()
    }
}

function Find-Python {
    # 按优先级搜索 Python
    foreach ($cmd in @("py", "python3", "python")) {
        try {
            if ($cmd -eq "py") {
                $ver = & py -3 --version 2>&1
            } else {
                $ver = & $cmd --version 2>&1
            }
            if ($ver -match "Python (\d+)\.(\d+)") {
                $major = [int]$Matches[1]
                $minor = [int]$Matches[2]
                if ($major -ge 3 -and $minor -ge 10) {
                    if ($cmd -eq "py") { return "py -3" }
                    return $cmd
                }
            }
        } catch {}
    }
    return $null
}

function Find-Node {
    try {
        $ver = & node --version 2>&1
        if ($ver -match "v(\d+)") {
            if ([int]$Matches[1] -ge 18) { return $true }
        }
    } catch {}
    return $false
}

function Find-Git {
    try {
        $ver = & git --version 2>&1
        if ($ver -match "git version") { return $true }
    } catch {}
    return $false
}

function Find-Claude {
    try {
        $ver = & claude --version 2>&1
        if ($LASTEXITCODE -eq 0) { return $true }
    } catch {}
    return $false
}

# =============================================================================
# GUI
# =============================================================================

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = "OpenNovel AI 写作系统 - 安装向导"
$form.Size = New-Object System.Drawing.Size(620, 640)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)

$y = 15

# --- 安装路径 ---
$lblPath = New-Object System.Windows.Forms.Label
$lblPath.Text = "安装路径："
$lblPath.Location = New-Object System.Drawing.Point(15, $y)
$lblPath.AutoSize = $true
$form.Controls.Add($lblPath)

$y += 22
$txtPath = New-Object System.Windows.Forms.TextBox
$txtPath.Text = "C:\OpenNovel"
$txtPath.Location = New-Object System.Drawing.Point(15, $y)
$txtPath.Size = New-Object System.Drawing.Size(460, 24)
$form.Controls.Add($txtPath)

$btnBrowse = New-Object System.Windows.Forms.Button
$btnBrowse.Text = "浏览..."
$btnBrowse.Location = New-Object System.Drawing.Point(485, ($y - 1))
$btnBrowse.Size = New-Object System.Drawing.Size(100, 26)
$form.Controls.Add($btnBrowse)

$btnBrowse.Add_Click({
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = "选择安装目录"
    $dlg.SelectedPath = $txtPath.Text
    if ($dlg.ShowDialog() -eq "OK") {
        $txtPath.Text = $dlg.SelectedPath
    }
})

# --- API Key ---
$y += 40
$lblKey = New-Object System.Windows.Forms.Label
$lblKey.Text = "Anthropic API Key："
$lblKey.Location = New-Object System.Drawing.Point(15, $y)
$lblKey.AutoSize = $true
$form.Controls.Add($lblKey)

$y += 22
$txtKey = New-Object System.Windows.Forms.TextBox
$txtKey.Location = New-Object System.Drawing.Point(15, $y)
$txtKey.Size = New-Object System.Drawing.Size(570, 24)
$txtKey.PasswordChar = [char]'*'
$form.Controls.Add($txtKey)

# --- Base URL ---
$y += 35
$lblUrl = New-Object System.Windows.Forms.Label
$lblUrl.Text = "API Base URL（如使用官方 API 无需修改）："
$lblUrl.Location = New-Object System.Drawing.Point(15, $y)
$lblUrl.AutoSize = $true
$form.Controls.Add($lblUrl)

$y += 22
$txtUrl = New-Object System.Windows.Forms.TextBox
$txtUrl.Text = "https://api.anthropic.com"
$txtUrl.Location = New-Object System.Drawing.Point(15, $y)
$txtUrl.Size = New-Object System.Drawing.Size(570, 24)
$form.Controls.Add($txtUrl)

# --- 安装按钮 ---
$y += 40
$btnInstall = New-Object System.Windows.Forms.Button
$btnInstall.Text = "开始安装"
$btnInstall.Location = New-Object System.Drawing.Point(15, $y)
$btnInstall.Size = New-Object System.Drawing.Size(570, 36)
$btnInstall.BackColor = [System.Drawing.Color]::FromArgb(45, 120, 220)
$btnInstall.ForeColor = [System.Drawing.Color]::White
$btnInstall.FlatStyle = "Flat"
$form.Controls.Add($btnInstall)

# --- 进度条 ---
$y += 48
$script:progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Location = New-Object System.Drawing.Point(15, $y)
$progressBar.Size = New-Object System.Drawing.Size(570, 22)
$progressBar.Minimum = 0
$progressBar.Maximum = 100
$form.Controls.Add($progressBar)

# --- 日志 ---
$y += 32
$script:txtLog = New-Object System.Windows.Forms.TextBox
$txtLog.Multiline = $true
$txtLog.ScrollBars = "Vertical"
$txtLog.ReadOnly = $true
$txtLog.Location = New-Object System.Drawing.Point(15, $y)
$txtLog.Size = New-Object System.Drawing.Size(570, 240)
$txtLog.Font = New-Object System.Drawing.Font("Consolas", 8.5)
$form.Controls.Add($txtLog)

# =============================================================================
# 安装逻辑
# =============================================================================

$btnInstall.Add_Click({
    $installDir = $txtPath.Text.Trim()
    $apiKey     = $txtKey.Text.Trim()
    $baseUrl    = $txtUrl.Text.Trim()

    # --- 校验输入 ---
    if ([string]::IsNullOrEmpty($apiKey)) {
        [System.Windows.Forms.MessageBox]::Show("请输入 API Key。", "提示", "OK", "Warning")
        return
    }
    if ([string]::IsNullOrEmpty($installDir)) {
        [System.Windows.Forms.MessageBox]::Show("请输入安装路径。", "提示", "OK", "Warning")
        return
    }

    # 禁用按钮防止重复点击
    $btnInstall.Enabled = $false
    $txtPath.ReadOnly = $true
    $txtKey.ReadOnly = $true
    $txtUrl.ReadOnly = $true

    try {
        # =====================================================================
        # Step 1: Python
        # =====================================================================
        Set-Progress 5
        Write-Log "[1/10] 检测 Python ..."
        $pythonCmd = Find-Python

        if ($pythonCmd) {
            Write-Log "  √ 已找到 Python ($pythonCmd)"
        } else {
            Write-Log "  未检测到 Python >= 3.10，正在安装 Python 3.12 ..."
            $installed = $false

            # 尝试 winget
            try {
                $wingetVer = & winget --version 2>&1
                if ($LASTEXITCODE -eq 0) {
                    Write-Log "  使用 winget 安装 ..."
                    & winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements 2>&1 | ForEach-Object { Write-Log "  $_" }
                    Refresh-Path
                    $pythonCmd = Find-Python
                    if ($pythonCmd) { $installed = $true }
                }
            } catch {}

            # 回退：直接下载安装
            if (-not $installed) {
                Write-Log "  winget 不可用，正在下载 Python 安装包 ..."
                $pyUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
                $pyInstaller = "$env:TEMP\python-3.12.8-amd64.exe"
                [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
                (New-Object System.Net.WebClient).DownloadFile($pyUrl, $pyInstaller)
                Write-Log "  下载完成，正在静默安装 ..."
                Start-Process -FilePath $pyInstaller -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1" -Wait
                Remove-Item $pyInstaller -Force -ErrorAction SilentlyContinue
                Refresh-Path
                $pythonCmd = Find-Python
            }

            if (-not $pythonCmd) {
                throw "Python 安装失败，请手动安装 Python 3.10+ 后重试。"
            }
            Write-Log "  √ Python 安装完成 ($pythonCmd)"
        }

        # =====================================================================
        # Step 2: Node.js
        # =====================================================================
        Set-Progress 15
        Write-Log "[2/10] 检测 Node.js ..."

        if (Find-Node) {
            Write-Log "  √ 已找到 Node.js"
        } else {
            Write-Log "  未检测到 Node.js，正在安装 Node.js 22 LTS ..."
            $installed = $false

            # 尝试 winget
            try {
                $wingetVer = & winget --version 2>&1
                if ($LASTEXITCODE -eq 0) {
                    Write-Log "  使用 winget 安装 ..."
                    & winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements 2>&1 | ForEach-Object { Write-Log "  $_" }
                    Refresh-Path
                    if (Find-Node) { $installed = $true }
                }
            } catch {}

            # 回退：MSI 安装
            if (-not $installed) {
                Write-Log "  winget 不可用，正在下载 Node.js MSI ..."
                $nodeUrl = "https://nodejs.org/dist/v22.14.0/node-v22.14.0-x64.msi"
                $nodeMsi = "$env:TEMP\node-v22.14.0-x64.msi"
                (New-Object System.Net.WebClient).DownloadFile($nodeUrl, $nodeMsi)
                Write-Log "  下载完成，正在静默安装 ..."
                Start-Process "msiexec.exe" -ArgumentList "/i `"$nodeMsi`" /qn" -Wait
                Remove-Item $nodeMsi -Force -ErrorAction SilentlyContinue
                Refresh-Path
            }

            if (-not (Find-Node)) {
                throw "Node.js 安装失败，请手动安装 Node.js 18+ 后重试。"
            }
            Write-Log "  √ Node.js 安装完成"
        }

        # =====================================================================
        # Step 3: Git (Claude Code CLI 强制依赖 Git Bash)
        # =====================================================================
        Set-Progress 22
        Write-Log "[3/10] 检测 Git ..."

        if (Find-Git) {
            Write-Log "  √ 已找到 Git"
        } else {
            Write-Log "  未检测到 Git，正在安装（Claude Code 需要 Git Bash）..."
            $installed = $false

            # 尝试 winget
            try {
                $wingetVer = & winget --version 2>&1
                if ($LASTEXITCODE -eq 0) {
                    Write-Log "  使用 winget 安装 ..."
                    & winget install Git.Git --silent --accept-package-agreements --accept-source-agreements 2>&1 | ForEach-Object { Write-Log "  $_" }
                    Refresh-Path
                    if (Find-Git) { $installed = $true }
                }
            } catch {}

            # 回退：直接下载安装
            if (-not $installed) {
                Write-Log "  winget 不可用，正在下载 Git 安装包 ..."
                $gitUrl = "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.2/Git-2.47.1.2-64-bit.exe"
                $gitInstaller = "$env:TEMP\Git-installer.exe"
                (New-Object System.Net.WebClient).DownloadFile($gitUrl, $gitInstaller)
                Write-Log "  下载完成，正在静默安装 ..."
                Start-Process -FilePath $gitInstaller -ArgumentList "/VERYSILENT /NORESTART /NOCANCEL /SP- /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS" -Wait
                Remove-Item $gitInstaller -Force -ErrorAction SilentlyContinue
                Refresh-Path
            }

            if (-not (Find-Git)) {
                throw "Git 安装失败，请手动安装 Git (https://git-scm.com/downloads/win) 后重试。"
            }
            Write-Log "  √ Git 安装完成"
        }

        # =====================================================================
        # Step 4: Claude Code CLI
        # =====================================================================
        Set-Progress 25
        Write-Log "[4/10] 检测 Claude Code CLI ..."

        if (Find-Claude) {
            Write-Log "  √ 已找到 Claude Code CLI"
        } else {
            Write-Log "  正在安装 Claude Code CLI ..."
            & npm install -g @anthropic-ai/claude-code 2>&1 | ForEach-Object { Write-Log "  $_" }
            Refresh-Path
            if (-not (Find-Claude)) {
                Write-Log "  ! 警告：Claude Code CLI 安装可能未完成，请稍后手动运行 npm install -g @anthropic-ai/claude-code"
            } else {
                Write-Log "  √ Claude Code CLI 安装完成"
            }
        }

        # =====================================================================
        # Step 5: 配置 Claude Code settings.json（提前，初始化需要 API Key）
        # =====================================================================
        Set-Progress 32
        Write-Log "[5/10] 配置 Claude Code ..."

        $claudeDir = "$env:USERPROFILE\.claude"
        $settingsPath = "$claudeDir\settings.json"

        if (Test-Path $settingsPath) {
            try {
                $settings = Get-Content $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
            } catch {
                Copy-Item $settingsPath "$settingsPath.bak" -Force
                Write-Log "  ! 已有 settings.json 解析失败，已备份为 settings.json.bak"
                $settings = New-Object PSObject
            }
        } else {
            New-Item -Path $claudeDir -ItemType Directory -Force | Out-Null
            $settings = New-Object PSObject
        }

        # 确保 env 属性存在
        if (-not ($settings.PSObject.Properties.Name -contains "env")) {
            $settings | Add-Member -NotePropertyName "env" -NotePropertyValue (New-Object PSObject)
        }

        # 写入/更新 API Key 和 Base URL
        $envObj = $settings.env
        if ($envObj.PSObject.Properties.Name -contains "ANTHROPIC_AUTH_TOKEN") {
            $envObj.ANTHROPIC_AUTH_TOKEN = $apiKey
        } else {
            $envObj | Add-Member -NotePropertyName "ANTHROPIC_AUTH_TOKEN" -NotePropertyValue $apiKey
        }

        if ($envObj.PSObject.Properties.Name -contains "ANTHROPIC_BASE_URL") {
            $envObj.ANTHROPIC_BASE_URL = $baseUrl
        } else {
            $envObj | Add-Member -NotePropertyName "ANTHROPIC_BASE_URL" -NotePropertyValue $baseUrl
        }

        $settings | ConvertTo-Json -Depth 10 | Set-Content $settingsPath -Encoding UTF8
        Write-Log "  √ Claude Code 配置已写入 $settingsPath"

        # =====================================================================
        # Step 6: 初始化 Claude Code（首次运行需接受服务条款）
        # =====================================================================
        Set-Progress 38
        Write-Log "[6/10] 初始化 Claude Code ..."

        # 先检测是否已初始化（claude --version 能正常执行说明 ToS 已接受）
        $needInit = $false
        try {
            $verOut = & claude --version 2>&1
            if ($LASTEXITCODE -ne 0) { $needInit = $true }
        } catch {
            $needInit = $true
        }

        if ($needInit) {
            Write-Log "  Claude Code 需要首次初始化（接受服务条款）"
            Write-Log "  即将打开终端，请按照提示操作 ..."

            # 生成临时初始化脚本
            $initBatPath = "$env:TEMP\opennovel_claude_init.bat"
            $initBatContent = @"
@echo off
chcp 65001 >nul
echo.
echo  ================================================
echo    Claude Code 首次初始化
echo    请按照提示操作（接受服务条款等）
echo    完成后输入 /exit 退出即可
echo  ================================================
echo.
claude
echo.
echo  初始化完成！此窗口将自动关闭 ...
timeout /t 3 >nul
"@
            Set-Content $initBatPath -Value $initBatContent -Encoding ASCII
            Start-Process cmd -ArgumentList "/c `"$initBatPath`"" -Wait
            Remove-Item $initBatPath -Force -ErrorAction SilentlyContinue
            Refresh-Path

            # 验证初始化是否成功
            try {
                $verOut2 = & claude --version 2>&1
                if ($LASTEXITCODE -eq 0) {
                    Write-Log "  √ Claude Code 初始化完成"
                } else {
                    Write-Log "  ! 警告：Claude Code 可能未完全初始化，首次运行时可能需要再次设置"
                }
            } catch {
                Write-Log "  ! 警告：Claude Code 可能未完全初始化，首次运行时可能需要再次设置"
            }
        } else {
            Write-Log "  √ Claude Code 已初始化"
        }

        # =====================================================================
        # Step 7: 复制项目源码
        # =====================================================================
        Set-Progress 45
        Write-Log "[7/10] 复制项目文件到 $installDir ..."

        if (-not (Test-Path $installDir)) {
            New-Item -Path $installDir -ItemType Directory -Force | Out-Null
        }

        # 使用 robocopy 复制，排除不需要的目录/文件
        $robocopyArgs = @(
            "`"$ScriptRoot`""
            "`"$installDir`""
            "/E"                        # 递归复制
            "/NFL"                      # 不列出文件名
            "/NDL"                      # 不列出目录名
            "/NJH"                      # 不打印 job header
            "/NJS"                      # 不打印 job summary
            "/XD", ".git", ".venv", "data", "__pycache__", "opennovel.egg-info", ".claude"
            "/XF", "*.pyc", ".env"
        )
        $robocopyCmd = "robocopy $($robocopyArgs -join ' ')"
        cmd /c $robocopyCmd 2>&1 | Out-Null
        # robocopy 退出码 < 8 表示成功
        Write-Log "  √ 文件复制完成"

        # =====================================================================
        # Step 8: 创建虚拟环境 + 安装依赖
        # =====================================================================
        Set-Progress 55
        Write-Log "[8/10] 创建 Python 虚拟环境 ..."

        $venvDir = "$installDir\.venv"
        if ($pythonCmd -eq "py -3") {
            & py -3 -m venv $venvDir 2>&1 | ForEach-Object { Write-Log "  $_" }
        } else {
            & $pythonCmd -m venv $venvDir 2>&1 | ForEach-Object { Write-Log "  $_" }
        }

        if (-not (Test-Path "$venvDir\Scripts\pip.exe")) {
            throw "虚拟环境创建失败。"
        }
        Write-Log "  √ 虚拟环境已创建"

        Set-Progress 62
        Write-Log "  正在安装 Python 依赖（可能需要几分钟）..."
        & "$venvDir\Scripts\pip.exe" install -e "$installDir" 2>&1 | ForEach-Object { Write-Log "  $_" }
        Write-Log "  √ Python 依赖安装完成"

        # =====================================================================
        # Step 9: 安装 Playwright Chromium
        # =====================================================================
        Set-Progress 72
        Write-Log "[9/10] 安装 Playwright Chromium 浏览器 ..."
        & "$venvDir\Scripts\playwright.exe" install chromium 2>&1 | ForEach-Object { Write-Log "  $_" }
        Write-Log "  √ Playwright Chromium 安装完成"

        # =====================================================================
        # Step 10: 生成 .env + 启动器 + 快捷方式 + 卸载器
        # =====================================================================
        Set-Progress 82
        Write-Log "[10/10] 生成启动器和快捷方式 ..."

        # --- .env 配置文件 ---
        $envExample = "$installDir\.env.example"
        $envFile    = "$installDir\.env"
        if (Test-Path $envExample) {
            Copy-Item $envExample $envFile -Force
            Write-Log "  √ .env 文件已从模板生成"
        } else {
            Write-Log "  ! .env.example 不存在，跳过"
        }

        # --- opennovel.bat ---
        $launcherContent = @"
@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python.exe -m cli.main %*
"@
        Set-Content "$installDir\opennovel.bat" -Value $launcherContent -Encoding ASCII
        Write-Log "  √ 启动器 opennovel.bat 已生成"

        # --- setup-browser.bat（番茄小说登录）---
        $setupBrowserContent = @"
@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动浏览器，请扫码登录番茄小说作家后台...
.venv\Scripts\python.exe -m cli.main setup-browser
pause
"@
        Set-Content "$installDir\setup-browser.bat" -Value $setupBrowserContent -Encoding ASCII
        Write-Log "  √ 番茄登录器 setup-browser.bat 已生成"

        # --- 桌面快捷方式 ---
        $desktopPath = [Environment]::GetFolderPath("Desktop")
        $shortcutPath = "$desktopPath\OpenNovel.lnk"
        $wshell = New-Object -ComObject WScript.Shell
        $shortcut = $wshell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = "$installDir\opennovel.bat"
        $shortcut.WorkingDirectory = $installDir
        $shortcut.Description = "OpenNovel AI 写作系统"
        $shortcut.Save()
        Write-Log "  √ 桌面快捷方式已创建"

        # --- 复制卸载脚本 + 生成 uninstall.bat ---
        $uninstallSrc = "$ScriptRoot\installer\uninstall.ps1"
        if (Test-Path $uninstallSrc) {
            Copy-Item $uninstallSrc "$installDir\uninstall.ps1" -Force
        }

        $uninstallBat = @"
@echo off
chcp 65001 >nul
powershell -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
pause
"@
        Set-Content "$installDir\uninstall.bat" -Value $uninstallBat -Encoding ASCII
        Write-Log "  √ 卸载器已生成"

        # =====================================================================
        # 完成
        # =====================================================================
        Set-Progress 100
        Write-Log ""
        Write-Log "========================================="
        Write-Log "  安装完成！"
        Write-Log "  安装目录：$installDir"
        Write-Log ""
        Write-Log "  使用方式："
        Write-Log "  1. 双击桌面 OpenNovel 快捷方式即可开始写作"
        Write-Log "  2. 如需上传番茄小说，先双击 setup-browser.bat 扫码登录"
        Write-Log "========================================="

        [System.Windows.Forms.MessageBox]::Show(
            "安装完成！`n`n使用方式：`n1. 双击桌面 OpenNovel 快捷方式开始写作`n2. 如需上传番茄小说，先双击安装目录下的 setup-browser.bat 扫码登录`n`n安装目录：$installDir",
            "安装成功",
            "OK",
            "Information"
        )

    } catch {
        Write-Log ""
        Write-Log "!!! 安装出错：$($_.Exception.Message)"
        Write-Log "请查看上方日志排查问题。"
        [System.Windows.Forms.MessageBox]::Show(
            "安装失败：$($_.Exception.Message)`n`n请查看日志了解详情。",
            "安装出错",
            "OK",
            "Error"
        )
    } finally {
        $btnInstall.Enabled = $true
        $txtPath.ReadOnly = $false
        $txtKey.ReadOnly = $false
        $txtUrl.ReadOnly = $false
    }
})

# --- 显示窗口 ---
$form.Add_Shown({ $form.Activate() })
[void]$form.ShowDialog()

