@echo off
rem DocGuard one-click deploy entry. Just double-click this file.
rem It launches deploy\deploy.ps1 which self-elevates (UAC prompt will appear).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\deploy.ps1"
