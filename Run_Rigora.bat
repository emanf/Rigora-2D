@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "RIGORA_EXIT_CODE=1"
set "RIGORA_PUSHED=0"
set "RIGORA_PAUSE=1"
if "%RIGORA_NO_PAUSE%"=="1" set "RIGORA_PAUSE=0"
if "%~1"=="--no-pause" set "RIGORA_PAUSE=0"

pushd "%~dp0"
if errorlevel 1 goto location_error
set "RIGORA_PUSHED=1"
if not exist ".venv\Scripts\python.exe" goto missing_environment
".venv\Scripts\python.exe" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('rigora') is not None else 1)"
if errorlevel 1 goto missing_package

rem Python consumes the optional first flag so all other quoted arguments stay intact.
".venv\Scripts\python.exe" -c "import sys; from rigora.interfaces.cli.main import main; raise SystemExit(main(sys.argv[2:] if sys.argv[1:2] == ['--no-pause'] else sys.argv[1:]))" %*
set "RIGORA_EXIT_CODE=%ERRORLEVEL%"
if not "%RIGORA_EXIT_CODE%"=="0" echo ERROR: Rigora exited with code %RIGORA_EXIT_CODE%.
goto finish

:missing_environment
echo ERROR: The local Python environment is missing.
goto setup_advice

:missing_package
echo ERROR: Rigora is not installed in the local Python environment.

:setup_advice
echo Run this command from "%~dp0" first:
echo     uv sync --locked --extra gui
goto finish

:location_error
echo ERROR: Could not open the Rigora directory "%~dp0".

:finish
if "%RIGORA_PUSHED%"=="1" popd
if not "%RIGORA_EXIT_CODE%"=="0" if "%RIGORA_PAUSE%"=="1" pause
endlocal & exit /b %RIGORA_EXIT_CODE%
