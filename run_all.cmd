@echo off
rem Scheduled-task wrapper for the eljam3ia pipeline.
rem Runs from its own directory so Task Scheduler's working dir doesn't matter.
cd /d "%~dp0"
if not exist output mkdir output
echo [%date% %time%] pipeline start >> "output\scheduler.log"
py run_all.py >> "output\scheduler.log" 2>&1
echo [%date% %time%] pipeline done (exit %errorlevel%) >> "output\scheduler.log"
