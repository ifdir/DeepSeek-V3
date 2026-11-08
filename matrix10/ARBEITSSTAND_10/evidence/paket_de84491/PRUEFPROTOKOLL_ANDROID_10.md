# Android-aarch64-Paket 10 (abgeleitet vom geprüften Linux-Paket de84491)
**Status:** GEBAUT, AUF ANDROID UNGETESTET.

**Hier geprüft:**
- SHA-256 und ZIP-Integrität stimmen.
- `diff -r` gegen das Linux-Paket: Abweichend sind nur die Rust-Bibliothek (ELF ARM aarch64, NEEDED auf bionic, zwei Exporte) und die Android-Felder in `MATRIX10_STAND10_STATUS.json`.

**Nicht geprüft:** Laden, Start und Abnahme auf Android (NICHT_PRÜFBAR, weil kein Gerät verfügbar ist).
