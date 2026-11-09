@echo off
setlocal
cd /d "%~dp0"
title MATRIX10 - Unabhaengige Freigabesperre - KEINE Produktfreigabe
chcp 65001 >nul 2>nul
echo ===============================================
echo MATRIX10 - TECHNISCHE FREIGABESPERRE
echo Original-P25 wird NICHT gestartet oder veraendert.
echo Ergebnisse werden in einem neuen Ordner angelegt.
echo Fehlende Tests gelten NICHT als bestanden.
echo ===============================================
where py >nul 2>nul
if not errorlevel 1 (
  py -3 FREIGABE_PRUEFEN.py --install-dependencies
) else (
  where python >nul 2>nul
  if not errorlevel 1 (
    python FREIGABE_PRUEFEN.py --install-dependencies
  ) else (
    echo ROT: Python 3 fehlt. Keine Produktfreigabe.
    set "GATE_PYTHON_FEHLT=1"
  )
)
set "GATE_EXIT=%errorlevel%"
if defined GATE_PYTHON_FEHLT set "GATE_EXIT=3"
echo.
echo Pruefprogramm Exitcode: %GATE_EXIT%
echo WICHTIG: ERGEBNIS_LESEN.txt im neuesten ERGEBNIS-Ordner lesen.
echo Die Originaldatenbank wird NICHT benutzt.
echo.
pause
endlocal
