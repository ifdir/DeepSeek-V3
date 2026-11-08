# Prüfprotokoll Android-aarch64-Paket (abgeleitet von Linux-Paket 9b94cb8)

**Status:** GEBAUT, AUF ANDROID UNGETESTET. Gesamtstatus ROT, keine Produktfreigabe.

## Anlass
Das Linux-Paket wurde auf einem Android-Handy gestartet und lieferte `503 NATIVE_BOUNDARY_UNAVAILABLE`.

Ursache: Das Linux-Paket enthält eine x86_64-Rust-Bibliothek, die auf ARM nicht geladen werden kann. Der Pfad ist fail-closed, so wie vorgesehen. Das Paket war ausdrücklich nur für Linux x86_64 deklariert.

## Bau
`tools/baue_android_08.sh <linux-paket.zip> <ausgabe>`
- Die Crate des Pakets wird für `aarch64-linux-android` gebaut. Linker ist Zig 0.17.1; bionic wird per DT_NEEDED zur Laufzeit geliefert; LLVM-libunwind ist statisch eingebunden.
- Kein NDK, weil das NDK über den Proxy blockiert ist.

## Geprüft (hier, ohne Gerät)
- SHA-256 und ZIP-Integrität stimmen.
- `diff -r` gegen das frisch entpackte Linux-Paket zeigt nur drei Abweichungen:
  - `libmatrix_boundary_core.so`,
  - `MATRIX10_STAND08_STATUS.json` (um Android-Felder ergänzt),
  - neue Datei `MATRIX10_STAND08_START_ANDROID.txt`.
- Die Bibliothek ist ein ELF für ARM aarch64.
  - NEEDED: libc.so, libdl.so, libm.so, liblog.so.
  - Sie exportiert nur `matrix_boundary_abi_version` und `matrix_boundary_check`.
  - Es gibt kein musl-Symbol `__errno_location` und kein TLS-Segment.
  - Die offenen Symbole sind die bionic-Namen, die in STATUS.json gelistet sind.
- Das Paket enthält keine weitere Binärdatei.

## Nicht geprüft
- Laden der Bibliothek auf echtem Android oder bionic.
- Start, Live-Abnahme und Tests auf Android.

Diese Punkte sind NICHT_PRÜFBAR, weil kein Gerät oder Emulator zur Verfügung stand. Die Startanleitung nennt eine Selbstprüfung (`Rust OK 3`) und als Ausweichweg den Bau der Bibliothek auf dem Gerät (`pkg install rust`).
