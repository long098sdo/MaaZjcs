@echo off
cd /d "%~dp0"
setlocal
if exist "%~dp0portable\python\pythonw.exe" (
    set "DOTNET_ROOT=%~dp0portable\dotnet"
    set "DOTNET_ROOT_X64=%~dp0portable\dotnet"
    set "PATH=%~dp0portable\python;%~dp0portable\dotnet;%PATH%"
    set "PYTHONHOME=%~dp0portable\python"
    set "PYTHONNOUSERSITE=1"
)
if exist "%~dp0tools\MaaZjcs.UpdateTitleHook.dll" (
    if defined DOTNET_STARTUP_HOOKS (
        set "DOTNET_STARTUP_HOOKS=%DOTNET_STARTUP_HOOKS%;%~dp0tools\MaaZjcs.UpdateTitleHook.dll"
    ) else (
        set "DOTNET_STARTUP_HOOKS=%~dp0tools\MaaZjcs.UpdateTitleHook.dll"
    )
)
start "" "%~dp0MFAAvalonia.exe"
