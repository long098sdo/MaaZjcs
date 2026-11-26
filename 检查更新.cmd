@echo off
cd /d "%~dp0"
if exist "%~dp0portable\python\pythonw.exe" (
    "%~dp0portable\python\pythonw.exe" "%~dp0tools\check_update.py" --manual
) else (
    where pythonw.exe >nul 2>&1
    if errorlevel 1 (
        echo Could not locate pythonw.exe. Run this file from the MaaZjcs portable package.
        pause
        exit /b 1
    )
    pythonw.exe "%~dp0tools\check_update.py" --manual
)
