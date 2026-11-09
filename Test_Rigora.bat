@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "RIGORA_EXIT_CODE=1"
set "RIGORA_PUSHED=0"
set "RIGORA_PAUSE=1"
if "%RIGORA_NO_PAUSE%"=="1" set "RIGORA_PAUSE=0"
if "%~1"=="--no-pause" set "RIGORA_PAUSE=0"
if not "%~1"=="" if not "%~1"=="--no-pause" goto usage_error
if not "%~2"=="" goto usage_error

pushd "%~dp0"
if errorlevel 1 goto location_error
set "RIGORA_PUSHED=1"
if not exist ".venv\Scripts\python.exe" goto missing_environment

".venv\Scripts\python.exe" -c "import importlib.util, sys; missing = [name for name in ('rigora', 'pytest', 'pytestqt', 'PySide6', 'ruff', 'mypy') if importlib.util.find_spec(name) is None]; print('Missing dependencies: ' + ', '.join(missing)) if missing else None; sys.exit(1 if missing else 0)"
if errorlevel 1 goto missing_dependencies
set "QT_QPA_PLATFORM=offscreen"

echo [1/4] Running pytest...
".venv\Scripts\python.exe" -m pytest
set "RIGORA_EXIT_CODE=%ERRORLEVEL%"
if not "%RIGORA_EXIT_CODE%"=="0" goto finish

echo [2/4] Checking lint...
".venv\Scripts\python.exe" -m ruff check .
set "RIGORA_EXIT_CODE=%ERRORLEVEL%"
if not "%RIGORA_EXIT_CODE%"=="0" goto finish

echo [3/4] Checking formatting...
".venv\Scripts\python.exe" -m ruff format --check .
set "RIGORA_EXIT_CODE=%ERRORLEVEL%"
if not "%RIGORA_EXIT_CODE%"=="0" goto finish

echo [4/4] Checking static types...
".venv\Scripts\python.exe" -m mypy
set "RIGORA_EXIT_CODE=%ERRORLEVEL%"
goto finish

:missing_environment
echo ERROR: The local Python environment is missing.
goto setup_advice

:missing_dependencies
echo ERROR: The local environment is missing required development dependencies.

:setup_advice
echo Run this command from "%~dp0" first:
echo     uv sync --locked --extra gui
set "RIGORA_EXIT_CODE=1"
goto finish

:location_error
echo ERROR: Could not open the Rigora directory "%~dp0".
goto finish

:usage_error
echo Usage: Test_Rigora.bat [--no-pause]
set "RIGORA_EXIT_CODE=2"

:finish
if "%RIGORA_PUSHED%"=="1" popd
if "%RIGORA_EXIT_CODE%"=="0" (
    echo All Rigora checks passed.
) else (
    echo ERROR: Rigora checks stopped with code %RIGORA_EXIT_CODE%.
)
if "%RIGORA_PAUSE%"=="1" pause
endlocal & exit /b %RIGORA_EXIT_CODE%
