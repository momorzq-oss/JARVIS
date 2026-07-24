@echo off
REM ========================================================================
REM JARVIS PyInstaller build script for Windows
REM Produces dist\JARVIS\JARVIS.exe as an onedir application.
REM ========================================================================
setlocal
cd /d "%~dp0"

set "PYTHON_CMD=py -3.12"

echo [JARVIS] Checking Python...
%PYTHON_CMD% --version
if errorlevel 1 (
    echo Python was not found. Install 64-bit Python 3.12.
    exit /b 1
)

echo.
echo [JARVIS] Installing dependencies...
%PYTHON_CMD% -m pip install --upgrade pip
%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed.
    exit /b 1
)

echo.
echo [JARVIS] Ensuring CPU-only Torch...
%PYTHON_CMD% -m pip install --upgrade torch --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 (
    echo CPU-only Torch installation failed.
    exit /b 1
)
%PYTHON_CMD% -c "import torch; assert '+cpu' in torch.__version__ and not torch.cuda.is_available(); print(torch.__version__, torch.cuda.is_available())"
if errorlevel 1 (
    echo Torch is not the required CPU-only build.
    exit /b 1
)

echo.
echo [JARVIS] Downloading wake-word models...
%PYTHON_CMD% -c "from openwakeword.utils import download_models; download_models()"
if errorlevel 1 (
    echo Wake-word model download failed.
    exit /b 1
)

echo.
echo [JARVIS] Verifying packaged runtime imports...
%PYTHON_CMD% -c "import scipy, numpy, openwakeword, faster_whisper, pkg_resources, piper; print('Runtime imports OK')"
if errorlevel 1 (
    echo Runtime import verification failed.
    exit /b 1
)

echo.
echo [JARVIS] Building JARVIS.exe...
set "LOCAL_ROUTER_ENABLED=1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "build\build_exe_watchdog.ps1"

if errorlevel 1 (
    echo Build failed. Review the PyInstaller output above.
    exit /b 1
)

echo.
echo ========================================================================
echo Build complete: dist\JARVIS\JARVIS.exe
echo Keep secrets outside the distribution; JARVIS loads its existing environment configuration.
echo JARVIS uses Edge, then Chrome, then permanent per-user Playwright Chromium.
echo ========================================================================
exit /b 0
