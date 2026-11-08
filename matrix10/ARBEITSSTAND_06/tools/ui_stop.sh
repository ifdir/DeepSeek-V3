#!/bin/bash
# Beendet alle Matrix-Serverprozesse (START.py, matrix_api.app) und weist nach:
# kein solcher Prozess mehr UND die Ports 5150/8180 verweigern Verbindungen.
pids() { ps -eo pid,cmd | grep -E "START\.py|matrix_api\.app" | grep -v grep | awk '{print $1}'; }
for p in $(pids); do kill $p 2>/dev/null; done
for i in $(seq 1 20); do [ -z "$(pids)" ] && break; sleep 0.5; done
for p in $(pids); do kill -9 $p 2>/dev/null; done
sleep 1
offen=0
for port in 5150 8180; do (exec 3<>/dev/tcp/127.0.0.1/$port) 2>/dev/null && offen=1; done
if [ -n "$(pids)" ] || [ $offen = 1 ]; then echo "STOP FEHLGESCHLAGEN: $(pids) offen=$offen"; exit 1; fi
exit 0
