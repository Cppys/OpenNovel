@echo off
chcp 65001 >nul
powershell -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1"
pause
