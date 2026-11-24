@echo off
setlocal
where cl.exe >nul 2>nul
if errorlevel 1 (
  echo Run this build from a Visual Studio Developer Command Prompt with MSVC available.
  exit /b 1
)
cl.exe /nologo /LD /W4 /O2 /I..\..\sdk example.c /Fe:example_native.dll
exit /b %errorlevel%
