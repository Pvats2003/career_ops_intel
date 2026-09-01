@echo off
REM Builds the Windows executable and (if Inno Setup is installed) the installer.
REM Run this from the `whatsapp_video_automation` project root:
REM     packaging\build.bat

setlocal

echo === InstaCore Sync build ===

if not exist ".venv" (
    echo Creating virtual environment...
    py -3.12 -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing dependencies...
pip install --upgrade pip >nul
pip install -r requirements.txt
pip install pyinstaller

echo Running tests before packaging...
pytest -q
if errorlevel 1 (
    echo Tests failed. Aborting build.
    exit /b 1
)

echo Building executable with PyInstaller...
pyinstaller packaging\pyinstaller.spec --clean --noconfirm
if errorlevel 1 (
    echo PyInstaller build failed.
    exit /b 1
)

echo Executable built at dist\InstaCoreSync\InstaCoreSync.exe

where iscc >nul 2>nul
if %errorlevel%==0 (
    echo Building installer with Inno Setup...
    iscc packaging\installer.iss
    echo Installer built at packaging\output\
) else (
    echo Inno Setup (iscc) not found on PATH - skipping installer build.
    echo Install it from https://jrsoftware.org/isinfo.php to produce a setup .exe.
)

echo === Build complete ===
endlocal
