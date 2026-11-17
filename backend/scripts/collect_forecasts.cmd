@echo off
rem Forecast archive collection. Called by Windows Task Scheduler (see docs/guides/forecast-archive.md).
rem Runs from the backend folder wherever it is called from, so .env and runtime are found.
setlocal
set PYTHONUTF8=1
cd /d "%~dp0.."
if not exist runtime mkdir runtime
echo [%date% %time%] collect start >> runtime\collect.log
".venv\Scripts\python.exe" -m scripts.forecast_archive collect >> runtime\collect.log 2>&1
set RESULT=%errorlevel%
echo [%date% %time%] collect end exit=%RESULT% >> runtime\collect.log
exit /b %RESULT%
