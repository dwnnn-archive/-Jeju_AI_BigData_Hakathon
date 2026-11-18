@echo off
rem Recent ASOS observation collection (yesterday and before). Called by Windows Task Scheduler.
setlocal
set PYTHONUTF8=1
cd /d "%~dp0.."
if not exist runtime mkdir runtime
echo [%date% %time%] asos start >> runtime\collect.log
".venv\Scripts\python.exe" -m scripts.collect_asos recent runtime\asos_recent >> runtime\collect.log 2>&1
set RESULT=%errorlevel%
echo [%date% %time%] asos end exit=%RESULT% >> runtime\collect.log
exit /b %RESULT%
