@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "RIGORA_PAUSE=1"
if "%RIGORA_NO_PAUSE%"=="1" set "RIGORA_PAUSE=0"
if "%~1"=="--no-pause" set "RIGORA_PAUSE=0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build_windows.ps1" %*
set "RIGORA_EXIT_CODE=%ERRORLEVEL%"
if not "%RIGORA_EXIT_CODE%"=="0" if "%RIGORA_PAUSE%"=="1" pause
endlocal & exit /b %RIGORA_EXIT_CODE%
