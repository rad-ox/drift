@echo off
setlocal
set "HERE=%~dp0"
if exist "%HERE%..\ui\drift-ask-ui.ps1" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%HERE%..\ui\drift-ask-ui.ps1" %*
  exit /b %ERRORLEVEL%
)
if exist "%HERE%..\share\drift\ui\drift-ask-ui.ps1" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%HERE%..\share\drift\ui\drift-ask-ui.ps1" %*
  exit /b %ERRORLEVEL%
)
if exist "%HERE%drift-ask-ui.ps1" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%HERE%drift-ask-ui.ps1" %*
  exit /b %ERRORLEVEL%
)
echo drift-ask-ui: missing drift-ask-ui.ps1 1>&2
exit /b 2
