@echo off
REM Nexuus Bot P0 probe: double-click me. No elevation, ever.
setlocal
set "PYTHONPATH=%~dp0..\src;%PYTHONPATH%"
where python >nul 2>nul
if %errorlevel%==0 (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    python -m agentdesk.probe %*
    goto :end
  )
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    py -3 -m agentdesk.probe %*
    goto :end
  )
)
echo Python not found on PATH or older than 3.10. Install Python 3.10+ for your user, or ask the owner.
:end
pause
