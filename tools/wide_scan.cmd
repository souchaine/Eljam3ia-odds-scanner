@echo off
REM Daily MEASUREMENT-ONLY scan over the wide odds window (pre-registered band test).
REM
REM --skip-betslips is LOAD-BEARING, not a convenience: --target is forwarded to both the scanner
REM and the betslip builder, so a run that built slips here would silently change what gets staked.
REM A run that builds no slips cannot mint a booking code and cannot alter a bet. Do not remove it.
REM
REM Window is 1.01..3.00 with zero tolerance. The pre-registered analysis bands start at 1.20;
REM rows below that are collected deliberately, because odds cannot be backfilled later.
REM See docs/superpowers/specs/2026-08-03-odds-window-widening-design.md

cd /d "%~dp0.."
set PY="C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe"
%PY% run_all.py --skip-betslips --target 1.01..3.00 --tolerance 0 > "output\wide_scan.log" 2>&1

REM Daily betslips, rebuilt OFFLINE from the matrix the scan just wrote. No second scan, no
REM bookmaker client, so this step cannot mint a booking code or place a bet. Legs are drawn from
REM the historical 1.25..1.50 window even though the scan is wider, so each day stays comparable
REM to the calibration log.
%PY% offline_betslips.py --legs 12 --slips 25 --window 1.25..1.50 >> "output\wide_scan.log" 2>&1
exit /b %ERRORLEVEL%
