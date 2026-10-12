@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
if exist ".venv\Scripts\python.exe" goto use_venv
where py >nul 2>nul
if not errorlevel 1 goto use_py
where python >nul 2>nul
if not errorlevel 1 goto use_python
echo Python was not found. Install Python 3.13 and enable "Add Python to PATH".
pause
exit /b 1

:use_venv
".venv\Scripts\python.exe" start.py --open-browser %*
goto finished

:use_py
py -3 start.py --open-browser %*
goto finished

:use_python
python start.py --open-browser %*

:finished
set "START_RESULT=%ERRORLEVEL%"
if not "%START_RESULT%"=="0" pause
exit /b %START_RESULT%
