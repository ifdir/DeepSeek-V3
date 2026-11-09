@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul 2>nul
title MATRIX10 - Pruefmaschine V1.2
echo ============================================================
echo MATRIX10 - PRUEFMASCHINE V1.2
echo Aendert keinen Produktcode und nie die Originaldatenbank.
echo HINWEIS: Dieser Windows-Start ist noch nicht auf Windows geprueft.
echo ============================================================
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% --version >nul 2>nul || (echo Python 3 fehlt. & pause & exit /b 3)
where node >nul 2>nul || (echo Node.js fehlt. & pause & exit /b 3)
if not exist ".pruefumgebung\Scripts\python.exe" (
  %PY% -m venv .pruefumgebung || (echo Python-Umgebung nicht anlegbar. & pause & exit /b 3)
  .pruefumgebung\Scripts\python.exe -m pip install --quiet flask pytest || (echo Flask/pytest nicht installierbar. & pause & exit /b 3)
)
if not exist ".playwright\node_modules\playwright" (
  call npm install --prefix .playwright playwright@1.63 --no-audit --no-fund || (echo Playwright nicht installierbar. & pause & exit /b 3)
  call npx --prefix .playwright playwright install chromium || (echo Chromium nicht installierbar. & pause & exit /b 3)
)
echo.
set /p KANDIDAT=Pfad zum Matrix10-ZIP:
set /p DB=Pfad zur Original-Datenbank (wird nur kopiert):
echo.
echo Pruefe Abnahme der Pruefmaschine ...
.pruefumgebung\Scripts\python.exe -I -c "import sys; sys.path.insert(0, '.'); import pm_auswertung as p; ok=p.manifest_pruefen(p.Path('.').resolve())[0]; print('Abnahme gueltig' if ok else 'KEINE gueltige Abnahme - erst SELBSTABNAHME_V12.py'); sys.exit(0 if ok else 3)" || (pause & exit /b 3)
echo Freigabepruefung (echtes Modell, ca. 70 Modellaufrufe) ...
.pruefumgebung\Scripts\python.exe -I FREIGABE_PRUEFEN_V12.py --kandidat "%KANDIDAT%" --db "%DB%" --modell live --aufnahme "MODELLAUFNAHME_%RANDOM%" --playwright "%CD%\.playwright\node_modules\playwright"
set "EXITCODE=%errorlevel%"
echo.
echo Exitcode: %EXITCODE%  (0 = GRUEN, 2 = ROT, 3 = BLOCKIERT)
echo Bericht: im neuesten Ordner ERGEBNIS_V12_... die Datei ERGEBNIS_LESEN.txt
pause
endlocal
