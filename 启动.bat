@echo off
rem Stardew Valley Mod Manager launcher (ASCII only: safe for any console code page)
setlocal
title Stardew Valley Mod Manager
cd /d "%~dp0"

set "PY="
call :probe py
call :probe python
if not defined PY (
    echo [ERROR] Python not found.
    echo         Install Python 3.10 or newer from https://www.python.org/downloads/
    echo         and tick "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

%PY% -c "import PySide6" >nul 2>nul
if errorlevel 1 (
    echo First run: installing dependency PySide6, please wait ...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        echo         Run manually:  %PY% -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
)

set "PYW=%PY%"
call set "PYW=%%PYW:python.exe=pythonw.exe%%"
call set "PYW=%%PYW:py.exe=pyw.exe%%"
start "StardewModManager" "%PYW%" "%~dp0main.py"
if errorlevel 1 (
    echo pythonw not available, starting with a console window ...
    %PY% "%~dp0main.py"
)
exit /b 0

:probe
for /f "delims=" %%P in ('where %1 2^>nul') do (
    if not defined PY (
        echo %%P| find /i "WindowsApps" >nul
        if errorlevel 1 (
            "%%P" -c "import sys" >nul 2>nul
            if not errorlevel 1 set "PY=%%P"
        )
    )
)
exit /b 0
