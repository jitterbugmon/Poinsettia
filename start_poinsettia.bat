@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_poinsettia.ps1"
if errorlevel 1 (
  echo.
  echo Poinsettia could not start. See the message above.
  pause
)
endlocal