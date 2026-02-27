# =============================================================================
# OpenNovel AI 写作系统 - 卸载脚本
# =============================================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# 安装目录 = 本脚本所在目录
$InstallDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- 确认对话框 ---
$confirmResult = [System.Windows.Forms.MessageBox]::Show(
    "确认卸载 OpenNovel？`n`n安装目录：$InstallDir",
    "卸载 OpenNovel",
    "YesNo",
    "Question"
)

if ($confirmResult -ne "Yes") {
    Write-Host "已取消卸载。"
    exit
}

# --- 是否保留数据 ---
$keepData = [System.Windows.Forms.MessageBox]::Show(
    "是否保留小说数据（data 目录）？`n`n包含：小说数据库、浏览器登录状态等。`n选择「是」保留数据，选择「否」全部删除。",
    "保留数据？",
    "YesNo",
    "Question"
)

Write-Host "正在卸载 OpenNovel ..."

# --- 删除桌面快捷方式 ---
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = "$desktopPath\OpenNovel.lnk"
if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath -Force
    Write-Host "  已删除桌面快捷方式"
}

# --- 删除安装目录 ---
if ($keepData -eq "Yes") {
    # 保留 data/ 目录，删除其他所有内容
    Write-Host "  保留 data 目录，删除其他文件 ..."
    Get-ChildItem -Path $InstallDir -Exclude "data" | ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Host "  已清理安装文件（data 目录已保留在 $InstallDir\data）"
} else {
    # 全部删除 — 先切出安装目录再删
    Set-Location $env:USERPROFILE
    Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  已删除安装目录 $InstallDir"
}

# --- 完成 ---
Write-Host ""
Write-Host "卸载完成。"
Write-Host "注意：Python、Node.js、Claude Code CLI 未被卸载（它们是系统级工具，可能被其他程序使用）。"

[System.Windows.Forms.MessageBox]::Show(
    "卸载完成！`n`nPython、Node.js、Claude Code CLI 未被卸载（系统级工具）。",
    "卸载完成",
    "OK",
    "Information"
)

