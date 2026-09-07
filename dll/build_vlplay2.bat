@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
cl /nologo /LD /O2 /W3 /DVL_NO_MUTEX VLPlay2.c /link /OUT:vlplay\VLPlay2.dll
echo BUILD_EXIT=%ERRORLEVEL%
