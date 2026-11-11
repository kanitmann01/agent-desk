@echo off
REM Agent Desk: start everything.
REM Double-click me for the dashboard (same as agent-desk.cmd).
REM From a terminal, "start.cmd dev" runs the development stack:
REM the Python API plus the live-reloading UI dev server, each in
REM its own window. Close the windows to stop. No elevation, ever.
setlocal
set "PYTHONPATH=%~dp0..\src;%PYTHONPATH%"

if /i "%~1"=="dev" goto dev
call "%~dp0agent-desk.cmd"
goto :end

:dev
where npm >nul 2>nul
if errorlevel 1 (
  echo node/npm not found. The committed UI bundle is served by the API anyway:
  echo start it with tools\agent-desk.cmd instead.
  goto :end
)
if not exist "%~dp0..\frontend\package.json" (
  echo frontend\ was not found, so there is no dev server to start.
  echo start it with tools\agent-desk.cmd instead.
  goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    start "Agent Desk API (dev)" cmd /k python -m agentdesk.server --port 8765
    goto ui
  )
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    start "Agent Desk API (dev)" cmd /k py -3 -m agentdesk.server --port 8765
    goto ui
  )
)
where uv >nul 2>nul
if %errorlevel%==0 (
  start "Agent Desk API (dev)" cmd /k uv run --no-project python -m agentdesk.server --port 8765
  goto ui
)
echo Python not found on PATH and no uv. Install Python 3.10+ for your user, or install uv.
goto :end

:ui
echo The API window prints the one-time start link (port 8765).
start "Agent Desk UI (dev)" cmd /k npm --prefix "%~dp0..\frontend" run dev
echo Open the UI at http://localhost:5173/static/spa/
echo If it says a session is required: open the API window's start link
echo with 127.0.0.1:8765 replaced by localhost:5173.
echo Close both windows to stop everything.

:end
endlocal
