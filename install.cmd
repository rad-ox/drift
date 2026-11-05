@echo off
rem DRIFT installer for Windows: double-click it or run it from a terminal.
rem Options go to install.ps1, e.g. "install.cmd -Help" or "install.cmd -Uninstall".
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
exit /b %ERRORLEVEL%
