@echo off
setlocal
pushd "%~dp0"
if not exist build mkdir build
where cl.exe >nul 2>nul
if errorlevel 1 (
  echo MSVC cl.exe not found. Use an x64 Visual Studio Developer Command Prompt.
  popd
  exit /b 1
)
cl.exe /nologo /LD /W4 /O2 /I..\..\sdk performance_probe.c /link /OUT:build\performance_probe.dll
set "RESULT=%errorlevel%"
popd
exit /b %RESULT%
