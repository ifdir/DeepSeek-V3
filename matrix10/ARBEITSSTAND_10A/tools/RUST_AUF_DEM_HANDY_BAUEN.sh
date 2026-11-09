#!/data/data/com.termux/files/usr/bin/bash
# Matrix10 - Rust-Einwilligungskern auf dem Android-Handy (Termux) selbst bauen und pruefen.
# Nur noetig, wenn START.py "[RUST-FEHLER] Einwilligungskern NICHT ladbar" meldet. Aufruf im Paketordner:
#   bash RUST_AUF_DEM_HANDY_BAUEN.sh
set -e
cd "$(dirname "$0")"
case "$(pwd)" in /sdcard*|/storage/*) echo "FEHLER: Paket liegt in $(pwd) - dort darf Android keine Bibliothek laden."; \
  echo "Bitte ins Termux-Home entpacken, z. B.: mkdir -p ~/m10 && cd ~/m10 && unzip /sdcard/Download/<ZIP>"; exit 2;; esac
command -v cargo >/dev/null 2>&1 || pkg install -y rust
( cd native_core/matrix-boundary-core && cargo build --release --offline --locked )
mkdir -p matrix_api/native
cp native_core/matrix-boundary-core/target/release/libmatrix_boundary_core.so matrix_api/native/libmatrix_boundary_core.so
python -c "import sys; sys.path.insert(0,'.'); from matrix_api import native_boundary as n; print(n.status())"
echo "Fertig. Jetzt: python START.py"
