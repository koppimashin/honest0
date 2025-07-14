@echo off
:: =====================================
:: 🛡️ Elevate to Admin (UAC Prompt)
:: =====================================
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"
if '%errorlevel%' NEQ '0' (
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    set params = %*:"=""
    echo UAC.ShellExecute "cmd.exe", "/c ""%~s0"" %params%", "", "runas", 1 >> "%temp%\getadmin.vbs"
    "%temp%\getadmin.vbs"
    del "%temp%\getadmin.vbs"
    exit /B
)

:: =====================================
:: 📦 Setup Virtual Environment
:: =====================================
pushd "%CD%"
CD /D "%~dp0"
set PYTHONPATH=%CD%

if not exist venv (
    echo [🔧] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ❌ Failed to create virtual environment.
        pause
        exit /B
    )
)

:: =====================================
:: ✅ Activate & Install Requirements
:: =====================================
call venv\Scripts\activate

if exist requirements.txt (
    echo [📦] Installing Python dependencies...
    pip install --upgrade pip
    pip install -r requirements.txt
)

echo [✅] Installation complete.
pause
exit /B
