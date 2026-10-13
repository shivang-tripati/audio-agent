@echo off
REM ===========================================================================
REM  Audio Agent - Build Script
REM
REM  Builds the three executables from the committed PyInstaller spec files:
REM    AudioAgent.spec        -> dist\AudioAgent\AudioAgent.exe + _internal\ (worker/supervisor)
REM    WindowsService.spec    -> dist\AudioAgentService.exe            (Windows service)
REM    Ui.spec                -> dist\AudioAgentUI.exe                 (tray UI)
REM
REM  Stages them where AudioAgentInstaller\installer.iss expects them and
REM  compiles the installer with Inno Setup 6.
REM
REM  NOTE: the committed .spec files are the source of truth and are never
REM  regenerated or deleted here. Build only writes to build\, dist\ and
REM  AudioAgentInstaller\dist|output - never to user configuration or logs
REM  (%ProgramData%\AudioAgent).
REM ===========================================================================

setlocal EnableDelayedExpansion

set "REPO=%~dp0"
if not defined PYTHON set "PYTHON=python"
if not defined PYINSTALLER set "PYINSTALLER=pyinstaller"
set "STAGE=AudioAgentInstaller\dist\AudioAgent"
set "ISCC="

echo ========================================
echo  Audio Agent - Build
echo ========================================
echo.

REM ---------------------------------------------------------------------------
REM  [1/7] Toolchain
REM ---------------------------------------------------------------------------
echo [1/7] Checking build tools...

%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not available as "%PYTHON%".
    echo Activate the project virtualenv or pass PYTHON=<path to python.exe> build.bat
    exit /b 1
)
%PYTHON% --version

%PYINSTALLER% --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: PyInstaller is not available.
    echo Install it with: %PYTHON% -m pip install -r requirements.txt
    exit /b 1
)
for /f "delims=" %%v in ('%PYINSTALLER% --version') do echo PyInstaller %%v

REM Inno Setup 7 compiler - resolved, not hardcoded.
for /f "delims=" %%i in ('where ISCC.exe 2^>nul') do set "ISCC=%%i"
if not defined ISCC (
    if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
)
if not defined ISCC (
    if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
)
if defined ISCC (
    echo Inno Setup compiler: !ISCC!
) else (
    echo WARNING: ISCC.exe not found - the installer will NOT be compiled.
)

REM ---------------------------------------------------------------------------
REM  [2/7] Dependencies
REM ---------------------------------------------------------------------------
echo.
echo [2/7] Installing dependencies...
%PYTHON% -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    exit /b 1
)

REM ---------------------------------------------------------------------------
REM  [3/7] Clean previous output (spec files are never touched)
REM ---------------------------------------------------------------------------
echo.
echo [3/7] Cleaning previous build output...
if exist "build\AudioAgent" rmdir /s /q "build\AudioAgent"
if exist "dist" rmdir /s /q "dist"

REM ---------------------------------------------------------------------------
REM  [4/7] Build all three executables
REM ---------------------------------------------------------------------------
echo.
echo [4/7] Building executables...

echo  - AudioAgent (worker + supervisor, one-dir with _internal)
%PYINSTALLER% --noconfirm --clean AudioAgent.spec
if errorlevel 1 (
    echo ERROR: AudioAgent.spec build failed
    exit /b 1
)

echo  - AudioAgentService (Windows service)
%PYINSTALLER% --noconfirm --clean WindowsService.spec
if errorlevel 1 (
    echo ERROR: WindowsService.spec build failed
    exit /b 1
)

echo  - AudioAgentUI (tray)
%PYINSTALLER% --noconfirm --clean Ui.spec
if errorlevel 1 (
    echo ERROR: Ui.spec build failed
    exit /b 1
)

REM ---------------------------------------------------------------------------
REM  [5/7] Stage the layout installer.iss expects
REM ---------------------------------------------------------------------------
echo.
echo [5/7] Staging installer payload...

if not exist "dist\AudioAgent" (
    echo ERROR: dist\AudioAgent was not produced by AudioAgent.spec
    exit /b 1
)
copy /Y "dist\AudioAgentService.exe" "dist\AudioAgent\" >nul
if errorlevel 1 (
    echo ERROR: Failed to stage AudioAgentService.exe
    exit /b 1
)
copy /Y "dist\AudioAgentUI.exe" "dist\AudioAgent\" >nul
if errorlevel 1 (
    echo ERROR: Failed to stage AudioAgentUI.exe
    exit /b 1
)

if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%"
if errorlevel 1 (
    echo ERROR: Failed to create %STAGE%
    exit /b 1
)
xcopy "dist\AudioAgent\*" "%STAGE%\" /E /I /H /Y /Q >nul
if errorlevel 1 (
    echo ERROR: Failed to mirror dist\AudioAgent into %STAGE%
    exit /b 1
)

REM Verify the payload the installer actually depends on.
for %%F in (
    "dist\AudioAgent\AudioAgent.exe"
    "dist\AudioAgent\AudioAgentService.exe"
    "dist\AudioAgent\AudioAgentUI.exe"
    "dist\AudioAgent\_internal\vlc\libvlc.dll"
    "%STAGE%\AudioAgent.exe"
    "%STAGE%\AudioAgentService.exe"
    "%STAGE%\AudioAgentUI.exe"
    "%STAGE%\_internal\vlc\libvlc.dll"
) do (
    if not exist %%F (
        echo ERROR: Missing required artifact: %%F
        exit /b 1
    )
)
echo  - All executables and VLC runtime present.

REM ---------------------------------------------------------------------------
REM  [6/7] Compile the installer
REM ---------------------------------------------------------------------------
echo.
echo [6/7] Compiling installer...
if not defined ISCC (
    echo WARNING: skipping installer.
    echo          Install Inno Setup 7, or compile it manually with:
    echo            "%%ProgramFiles(x86)%%\Inno Setup 7\ISCC.exe" AudioAgentInstaller\installer.iss
    echo          Output: AudioAgentInstaller\output\AudioAgentSetup_^<version^>.exe
) else (
    "!ISCC!" "AudioAgentInstaller\installer.iss"
    if errorlevel 1 (
        echo ERROR: Inno Setup compilation failed
        exit /b 1
    )
)

REM ---------------------------------------------------------------------------
REM  [7/7] Summary
REM ---------------------------------------------------------------------------
echo.
echo [7/7] Build summary:
if exist "dist\AudioAgent\AudioAgent.exe"         echo   dist\AudioAgent\AudioAgent.exe
if exist "dist\AudioAgent\_internal\vlc\libvlc.dll" echo   dist\AudioAgent\_internal\vlc\libvlc.dll
if exist "dist\AudioAgentService.exe"              echo   dist\AudioAgentService.exe
if exist "dist\AudioAgentUI.exe"                   echo   dist\AudioAgentUI.exe
if exist "%STAGE%"                                 echo   %STAGE%
if exist "AudioAgentInstaller\output" (
    for /f "delims=" %%f in ('dir /b /o-d "AudioAgentInstaller\output\*.exe" 2^>nul') do (
        if not defined INSTALLER_FOUND echo   AudioAgentInstaller\output\%%f
        set "INSTALLER_FOUND=1"
    )
)
if not defined INSTALLER_FOUND echo   (no installer produced - see the warning above)

echo.
echo ========================================
echo  Build completed
echo ========================================
echo.
echo Bump #define MyAppVersion in AudioAgentInstaller\installer.iss to cut a release.
echo.
endlocal
exit /b 0