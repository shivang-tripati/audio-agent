@echo off
REM Windows Audio Agent - Build Script
REM Creates standalone executable using PyInstaller

echo ========================================
echo Windows Audio Agent - Build Script
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.9+ from https://www.python.org/
    pause
    exit /b 1
)

echo [1/5] Checking Python version...
python --version

REM Check if pip is available
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: pip is not installed
    pause
    exit /b 1
)

echo [2/5] Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo [3/5] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist AudioAgent.spec del AudioAgent.spec

echo [4/5] Building executable with PyInstaller...
pyinstaller --onefile ^
    --noconsole ^
    --name AudioAgent ^
    --icon=icon.ico ^
    --add-data "requirements.txt;." ^
    --hidden-import comtypes ^
    --hidden-import pycaw ^
    --hidden-import vlc ^
    main.py

if %errorlevel% neq 0 (
    echo ERROR: Build failed
    pause
    exit /b 1
)

echo [5/5] Creating deployment package...
if not exist deployment mkdir deployment
copy dist\AudioAgent.exe deployment\
copy requirements.txt deployment\
copy README.md deployment\ 2>nul

REM Create template config
echo Creating configuration template...
(
echo {
echo   "device_id": "CHANGE_ME",
echo   "branch_id": "CHANGE_ME",
echo   "server_url": "https://api.yourdomain.com",
echo   "token": "CHANGE_ME",
echo   "master_volume": 100,
echo   "branch_volume": 100,
echo   "heartbeat_interval": 45,
echo   "auto_start": true
echo }
) > deployment\agent_config.json.template

echo.
echo ========================================
echo Build completed successfully!
echo ========================================
echo.
echo Executable location: dist\AudioAgent.exe
echo Deployment package: deployment\
echo.
echo Next steps:
echo 1. Copy deployment\ folder to target machines
echo 2. Configure agent_config.json
echo 3. Set up auto-start (see Setup Guide)
echo.
pause