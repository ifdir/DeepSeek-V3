#!/bin/bash
# Stand 12: Android-Paket MIT DEINEN DATEN zusammenstellen (nur fuer die Uebergabe an dich, NIE ins Repository).
# Nimmt das gepruefte Android-Paket und data/matrix10.sqlite + .matrix10_db_initialized aus deinem letzten Upload
# (ohne Lock-Dateien) und legt einen deutlichen Hinweis bei: die Datenbank enthaelt deinen API-Schluessel unverschluesselt.
# Aufruf: mit_deinen_daten_11.sh <android-paket.zip> <ordner-mit-deinen-daten> <ausgabe.zip>
set -euo pipefail
PKG=$(realpath "$1"); DATEN=$(realpath "$2"); OUT=$(realpath -m "$3")
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
cd "$W" && unzip -q "$PKG"
N=$(basename "$OUT" .zip); mv "$(ls)" "$N"; mkdir -p "$N/data"
cp "$DATEN/matrix10.sqlite" "$DATEN/.matrix10_db_initialized" "$N/data/"
cat > "$N/ENTHAELT_DEINEN_SCHLUESSEL_NICHT_WEITERGEBEN.txt" <<'TXT'
ACHTUNG: Dieses Paket enthaelt deine Daten (data/matrix10.sqlite) - darin steht dein API-Schluessel UNVERSCHLUESSELT.
Nicht weitergeben, nicht hochladen, nicht in ein Git-Repository legen. Ist es doch passiert: Schluessel beim Anbieter
widerrufen und einen neuen unter "Konfiguration" eintragen.
TXT
rm -f "$OUT"; find "$N" -type f | LC_ALL=C sort | zip -q -X "$OUT" -@
echo "$OUT"
