@echo off
REM Agent Desk P0 probe: double-click me. No elevation, ever.
setlocal
set "PYTHONPATH=%~dp0..\src;%PYTHONPATH%"
where python >nul 2>nul
if %errorlevel%==0 (
  python -m agentdesk.probe %*
  goto :end
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m agentdesk.probe %*
  goto :end
)
echo Python not found on PATH. Install Python 3.10+ for your user, or ask the owner.
:end
pause
