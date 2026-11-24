@echo off
setlocal
set "PYTHONPATH=%~dp0src"
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 "%~dp0run.py" %*
) else (
  python "%~dp0run.py" %*
)
