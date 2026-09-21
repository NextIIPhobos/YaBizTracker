@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo YaBizTracker - Windows build
echo ============================================================

where py >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python Launcher "py" was not found.
    echo Install Python 3.10+ and enable the Python Launcher.
    goto :error
)

echo [1/7] Preparing virtual environment...
if not exist ".venv\Scripts\python.exe" py -3 -m venv ".venv"
if errorlevel 1 goto :error

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :error

echo [2/7] Updating build tooling...
python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :error
python -m pip install -r requirements.txt -r requirements-dev.txt
if errorlevel 1 goto :error

echo [3/7] Validating source tree...
python -m compileall -q main.py yabiztracker tests
if errorlevel 1 goto :error

if not exist "icon.png" (
    echo ERROR: icon.png was not found in the project root.
    goto :error
)

echo [4/7] Preparing Windows icon...
python -c "from PIL import Image; Image.open('icon.png').convert('RGBA').save('icon.ico', format='ICO', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
if errorlevel 1 goto :error

echo [5/7] Running quality checks...
set "QT_QPA_PLATFORM=offscreen"
python -m pytest -q tests
if errorlevel 1 goto :error
ruff check main.py yabiztracker tests
if errorlevel 1 goto :error

echo [6/7] Building YaBizTracker.exe...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
python -m PyInstaller --clean --noconfirm YaBizTracker.spec
if errorlevel 1 goto :error

if not exist "dist\YaBizTracker.exe" (
    echo ERROR: PyInstaller completed but dist\YaBizTracker.exe is missing.
    goto :error
)

echo [7/7] Build verification...
for %%F in ("dist\YaBizTracker.exe") do echo EXE size: %%~zF bytes
echo.
echo BUILD SUCCESSFUL.
echo Executable: %CD%\dist\YaBizTracker.exe
echo.
pause
exit /b 0

:error
echo.
echo ============================================================
echo BUILD FAILED
echo ============================================================
pause
exit /b 1
