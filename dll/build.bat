@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
where cl >nul 2>&1
if not errorlevel 1 goto :compile
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" goto :missing
set "VSTEMP=%TEMP%\vlaudio-vs-%RANDOM%-%RANDOM%.txt"
"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath > "%VSTEMP%"
set "VSROOT="
set /p "VSROOT=" < "%VSTEMP%"
del "%VSTEMP%" >nul 2>&1
if not defined VSROOT goto :missing
call "%VSROOT%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
:compile
if not exist "release" mkdir "release"
if errorlevel 1 exit /b 1
cl /nologo /LD /O2 /W4 /WX /MT /Fo:release\VLXInput.obj VLXInput.c /link /DEF:VLXInput.def /OUT:release\xinput1_4.dll /IMPLIB:release\VLXInput.lib
if errorlevel 1 exit /b 1
cl /nologo /LD /O2 /W4 /WX /MT /Fo:release\VLAudioLoader.obj VLAudioLoader.c /link /OUT:release\VLAudioLoader.dll /IMPLIB:release\VLAudioLoader.lib
if errorlevel 1 exit /b 1
cl /nologo /O2 /W4 /WX /MT /Fo:release\runtime_test.obj runtime_test.c /link /OUT:release\runtime_test.exe
if errorlevel 1 exit /b 1
cl /nologo /O2 /W4 /WX /MT /Fo:release\hook_stack_test.obj hook_stack_test.c /link /OUT:release\hook_stack_test.exe
exit /b %errorlevel%
:missing
echo Visual Studio C++ Build Tools x64 were not found. Run from an x64 Native Tools prompt.
exit /b 1
