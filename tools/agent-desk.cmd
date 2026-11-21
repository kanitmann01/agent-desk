@echo off
REM Agent Desk: double-click me. The dashboard opens in your browser.
REM No elevation, ever. No terminal stays open: the app runs windowless.
setlocal enabledelayedexpansion
set "PYTHONPATH=%~dp0..\src;%PYTHONPATH%"

where python >nul 2>nul
if %errorlevel%==0 (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    for /f "usebackq delims=" %%W in (`python -c "import os, sys; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))"`) do set "PYW=%%W"
    if exist "!PYW!" (
      start "" "!PYW!" -m agentdesk.server
      goto :end
    )
    start /min "" python -m agentdesk.server
    goto :end
  )
)

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    start /min "" py -3 -m agentdesk.server
    goto :end
  )
)

where uv >nul 2>nul
if %errorlevel%==0 (
  REM Windows trust store at bootstrap. Old and new uv spell it differently;
  REM both spellings are honored through the environment, unknown ones ignored.
  set "UV_SYSTEM_CERTS=1"
  set "UV_NATIVE_TLS=1"
  start /min "" uv run --no-project python -m agentdesk.server
  goto :end
)

echo Python not found on PATH and no uv. Install Python 3.10+ for your user, or install uv.
REM The reader of this message cannot fix it herself; hold the window the
REM way the probe does, so a double-click shows more than a flash.
pause
:end
endlocal
