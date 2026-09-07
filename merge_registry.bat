@echo off
setlocal DisableDelayedExpansion
REM The vendored cobra-tools constants loader raises on 3.10, so 3.11 is the floor.
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 goto :nopython
python -c "import numpy, imageio, bitarray, PIL" >nul 2>&1
if errorlevel 1 goto :nodeps
python "%~dp0merge_audio_registry.py" %*
set "RC=%errorlevel%"
echo.
if "%RC%"=="0" echo Done. Restart the game after installing the generated files.
if not "%RC%"=="0" echo Merge failed. See the error above; do not use an incomplete build.
if not defined VLAUDIO_NO_PAUSE pause
exit /b %RC%
:nopython
echo Python 3.11 or newer is required. Install Python and add it to PATH.
if not defined VLAUDIO_NO_PAUSE pause
exit /b 1
:nodeps
echo Missing required Python packages. Run this once, then try again:
echo.
echo     python -m pip install -r "%~dp0requirements.txt"
echo.
if not defined VLAUDIO_NO_PAUSE pause
exit /b 1
