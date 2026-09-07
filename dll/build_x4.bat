@echo off
call "%~dp0build.bat"
if errorlevel 1 exit /b 1
if not exist "%~dp0auto4" mkdir "%~dp0auto4"
copy /y "%~dp0release\xinput1_4.dll" "%~dp0auto4\xinput1_4.dll" >nul
exit /b %errorlevel%
