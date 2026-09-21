@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem YaBizTracker launcher.
rem Prefer the packaged GUI executable; otherwise run the source entry point
rem with pythonw so no console window is shown.

if exist "%~dp0dist\YaBizTracker.exe" (
    start "" "%~dp0dist\YaBizTracker.exe"
    exit /b 0
)

if exist "%~dp0YaBizTracker.exe" (
    start "" "%~dp0YaBizTracker.exe"
    exit /b 0
)

if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
    exit /b 0
)

where pyw.exe >nul 2>&1
if not errorlevel 1 (
    start "" pyw.exe -3 "%~dp0main.py"
    exit /b 0
)

where pythonw.exe >nul 2>&1
if not errorlevel 1 (
    start "" pythonw.exe "%~dp0main.py"
    exit /b 0
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command ^
  "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('YaBizTracker не найден. Сначала выполните build_windows.bat или установите Python 3.11+.','YaBizTracker')" >nul 2>&1
exit /b 1
