#!/bin/bash
# ui_start.sh <produktordner> <vorlage.sqlite> <logdatei>: erst alles stoppen (nachgewiesen), dann P25-START.py frisch.
# START.py nutzt fest <produktordner>/data/matrix10.sqlite; dorthin kommt eine KOPIE der Vorlage (nie die Original-DB).
"$(dirname "$0")/ui_stop.sh" || exit 2
R=$1; mkdir -p "$R/data"; cp "$2" "$R/data/matrix10.sqlite"
rm -f "$R/data/matrix10.sqlite-wal" "$R/data/matrix10.sqlite-shm" "$R/data/.matrix10_start.lock"
cd "$R" && MATRIX_API_PORT=5150 MATRIX_UI_PORT=8180 MATRIX_NO_OPEN=1 nohup python3 START.py > "$3" 2>&1 &
for i in $(seq 1 60); do curl -sf http://127.0.0.1:5150/api/health >/dev/null && curl -sf http://127.0.0.1:8180/ >/dev/null && break; sleep 1; done
API=$(ps -eo pid,etimes,cmd | grep -v grep | grep "matrix_api.app" | awk '{print $1":"$2"s"}')
echo "API-Prozess (pid:alter) $API; native: $([ -d "$R/matrix_api/native" ] && ls "$R/matrix_api/native" || echo NEIN)"
curl -sf http://127.0.0.1:5150/api/health >/dev/null
