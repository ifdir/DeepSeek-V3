# Android-aarch64-Paket 09 (abgeleitet vom geprüften Linux-Paket 7b71ab9)
**Status:** GEBAUT, AUF ANDROID UNGETESTET.

**Hier geprüft:**
- SHA-256 und ZIP-Integrität stimmen.
- `diff -r` gegen das Linux-Paket: Abweichend sind nur die Rust-Bibliothek und die Android-Felder in `MATRIX10_STAND09_STATUS.json`.
- Die Rust-Bibliothek ist ein ELF für ARM aarch64. NEEDED: libc.so, libdl.so, libm.so, liblog.so. Sie exportiert nur `matrix_boundary_abi_version` und `matrix_boundary_check`.
- Beide Startanleitungen (Linux, Android) liegen im Paket.

**Nicht geprüft:** Laden der Bibliothek, Start und Abnahme auf Android (NICHT_PRÜFBAR, weil kein Gerät verfügbar ist). Die Selbstprüfung auf dem Gerät steht in `MATRIX10_STAND09_START_ANDROID.txt`.
