@echo off
rem Build the MidiMCP Docker image and publish it to ghcr.io - free for public images.
rem Double-click this file, or run from a terminal:  scripts\publish-image.cmd [-NoPush] [-Owner name]
rem Needs Docker Desktop in Linux-containers mode and Git for Windows. Logic lives in publish-image.ps1.
setlocal
set "PS_EXE=powershell.exe"
where pwsh.exe >nul 2>&1 && set "PS_EXE=pwsh.exe"
"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish-image.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" goto success
powershell.exe -NoProfile -Command "Write-Host 'Publish FAILED - exit code %RC%. Scroll up for the red lines or open publish-image.log in the repo folder.' -ForegroundColor Red"
goto done
:success
powershell.exe -NoProfile -Command "Write-Host 'Publish finished successfully.' -ForegroundColor Green"
:done
echo.
pause
endlocal & exit /b %RC%
