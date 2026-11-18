@echo off
rem Day-ahead analysis once a day (targets tomorrow). Called by Windows Task Scheduler at 17:30.
rem Runs inside the backend folder so .env and runtime are found.
setlocal
set PYTHONUTF8=1
cd /d "%~dp0.."
if not exist runtime mkdir runtime
echo [%date% %time%] day-ahead start >> runtime\collect.log
".venv\Scripts\python.exe" -m scripts.run_day_ahead >> runtime\collect.log 2>&1
set RESULT=%errorlevel%
echo [%date% %time%] day-ahead end exit=%RESULT% >> runtime\collect.log
exit /b %RESULT%
