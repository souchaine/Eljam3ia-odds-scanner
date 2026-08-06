@echo off
REM Daily BETTING run: scans the historical window and MINTS 25 booking codes on eljam3ia.
REM
REM This is the only scheduled job that touches the bookmaker account. A booking code is a
REM RESERVATION, not a stake -- nothing is charged until a code is loaded and confirmed by hand in
REM the BETSLIP panel -- but the codes are real and appear on the account.
REM
REM Window is left at the scanner defaults (1.30..1.45 +/- 0.05 = 1.25..1.50) so every slip stays
REM comparable to the calibration log. 12 legs per slip.
REM
REM MEASURED EXPECTATION: -6.6% per leg over 10,202 graded observations / 518 matches, so a 12-fold
REM compounds to about -56% per unit staked, winning ~2.2% of the time. See docs/CALIBRATION-LOG.md.
REM To stop: schtasks /Change /TN "Eljam3ia Odds Pipeline" /DISABLE

cd /d "%~dp0.."
"C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe" run_all.py ^
    --legs 12 --slips 25 > "output\betting_run.log" 2>&1
exit /b %ERRORLEVEL%
