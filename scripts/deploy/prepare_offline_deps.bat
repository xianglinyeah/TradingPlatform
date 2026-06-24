@echo off
REM Offline deployment dependency preparation script (Windows)
REM Download all dependencies locally to avoid k8s container network requirements

setlocal

echo ========================================
echo Preparing Offline Deployment Dependencies (Windows)
echo ========================================

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..\..

echo Project root: %PROJECT_ROOT%
cd /d %PROJECT_ROOT%

REM 1. C# dependency preparation
echo.
echo [1/2] Preparing C# dependencies...
cd src\Execution.Service

echo   Cleaning old build...
if exist bin rmdir /s /q bin
if exist obj rmdir /s /q obj

echo   Restoring NuGet packages...
dotnet restore --packages packages

echo   Building publish...
dotnet publish -c Release -o bin\Release\net8.0\publish --no-restore

echo   [OK] C# dependencies prepared

REM 2. Python dependency preparation
echo.
echo [2/2] Preparing Python dependencies...
cd ..\..\src\strategy-engine

REM Create virtual environment
if not exist venv (
    echo   Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo   Activating virtual environment...
call venv\Scripts\activate.bat

REM Upgrade pip
echo   Upgrading pip...
python -m pip install --upgrade pip wheel

REM Clean old dependencies
if exist local-packages rmdir /s /q local-packages
mkdir local-packages

REM Download all dependencies
echo   Downloading pip dependencies...
if exist requirements.txt (
    pip download -r requirements.txt -d local-packages
    echo   [OK] Python dependencies prepared
) else (
    echo   [ERROR] requirements.txt not found
    exit /b 1
)

echo.
echo ========================================
echo Offline dependency preparation completed!
echo ========================================
echo.
echo Next step: Run deployment script
echo   cd %SCRIPT_DIR%
echo   deploy_all.bat
echo.

endlocal
