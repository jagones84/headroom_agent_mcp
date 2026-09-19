@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0.."
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"

if exist "%ROOT_DIR%\.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ROOT_DIR%\.env") do (
    if not "%%~A"=="" set "%%~A=%%~B"
  )
)

if defined PYTHONPATH (
  set "PYTHONPATH=%ROOT_DIR%\src;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%ROOT_DIR%\src"
)

if defined HEADROOM_AGENT_PYTHON (
  call "%HEADROOM_AGENT_PYTHON%" "%ROOT_DIR%\scripts\headroom_agent_stdio_windows.py" %*
) else (
  python "%ROOT_DIR%\scripts\headroom_agent_stdio_windows.py" %*
)
