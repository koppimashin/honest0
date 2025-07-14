@echo off
pushd "%CD%"
CD /D "%~dp0"

:: Set project root as PYTHONPATH for module resolution
set PYTHONPATH=%CD%

:: Activate virtual environment
call venv\Scripts\activate

:: Run the main app using pythonw.exe to suppress the console window
echo [🚀] Launching Stealth Assistant silently...
start "" venv\Scripts\pythonw.exe app\main.py

exit /B
