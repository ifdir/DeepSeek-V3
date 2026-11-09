# MATRIX10_RUST_ARBEITSSTAND_04_20261107

**ROT / BLOCKIERT. Quellstand mit Prüfergebnissen – KEIN INSTALLIERBARES UPDATE.**

## Inhalt

- `sources/`: Original-AMASTER, Matrix10.txt, SPS und verbindlicher Reparatur-Kettenvertrag.
- `integration/`: Rust-Quellkern, private FFI-Brücke und **nur zwei geänderte** V67-Python-Module (`repos.py`, `scene_state.py`); ohne neue API und ohne zweite Datenbank.
- `tests/`: Python-Adaptertests, Testorakel und die vorhandenen Rust-Tests im `integration/native_core`.
- `tools/`: Original-V67-Gegenproben, rekonstruierbares Stage, kontrollierter Offline-Build und tatsächliche SQLite-Native-Probe.
- `evidence/`: reale Logs und JSON zu Staging/Tests/Blockern, statische AMASTER-Codekarte.
- `patches/`: genaue Originaldifferenzen.
- `BAUBERICHT_04.md`: Ursachen, Prüfergebnisse, offene Schritte.

## Ablauf – nur für technische Prüfung, NICHT für Produktinstallation

Benötigt: exakt `MATRIX10_V67_ABHAENGIGKEIT_20261031.zip` (SHA-256 `5158df268ab7f9105428b26c90932998e5b7b10fb8a3926e97ff2c4aa382efed`). Zielordner darf nicht existieren.

```sh
python3 -B tools/stage_source_04.py /pfad/MATRIX10_V67_ABHAENGIGKEIT_20261031.zip /tmp/matrix04_fresh
python3 -B tools/build_native.py /tmp/matrix04_fresh/MATRIX10_V67_ABHAENGIGKEIT_20261031 --evidence-dir /tmp/matrix04_native_build
python3 -B tools/probe_native_sqlite_04.py /tmp/matrix04_fresh/MATRIX10_V67_ABHAENGIGKEIT_20261031 --output /tmp/matrix04_native_sqlite.json
```

Ohne `rustc`/`cargo` ist der Build **BLOCKIERT**, nicht bestanden. Rust-Unit-Tests sind bisher **0 ausgeführt**. Die Rust-Bibliothek muss explizit mit demselben FFI-ABI-Stand (2) in die rekonstruierte Prüfkopie gelangen. Nichts davon installiert, aktiviert oder ersetzt produktive Matrix10-Daten.

```sh
MATRIX10_V67_ROOT=/tmp/matrix04_fresh/MATRIX10_V67_ABHAENGIGKEIT_20261031 python3 -B -m unittest discover -s tests -p 'test_consent_projection_04.py' -v
python3 -B -m unittest discover -s tests -p 'test_transport_02.py' -v
python3 -B -m unittest discover -s tests -p 'test_consent_transport_03.py' -v
```

Python-Adaptertests simulieren den Rust-Rückkanal. Sie ersetzen weder Cargo-Tests noch die End-to-End-Abnahme gemäß AMASTER/Kettenvertrag. Die 4 neuen C04-Gegenproben sind **negative Nachweise gegen Original-V67**, nicht grüne Kandidatenprüfungen.
