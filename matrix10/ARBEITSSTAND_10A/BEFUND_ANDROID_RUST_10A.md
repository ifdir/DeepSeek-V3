# Stand 10a: Android-Ausfall „503 Rust-Schreibgrenze konnte nicht geladen werden“

## Befund (Screenshot 08.11. und Code)
- Auf dem Handy liefen die 1. Puppet-Eingabe und das echte Modell. Maras Antwort trägt „Synapsen …·llm“.
- Die 2. Eingabe („greift auf die Schenkel“) ist eine Berührung und braucht den Einwilligungskern. Erst dort lädt der Server die Rust-Bibliothek, verzögert in `native_boundary._load()`. Das Laden scheiterte, der Server antwortete mit 503, nichts wurde gespeichert.
- **Funktionsverlust gegenüber P25 auf Android.** Seit Stand 06 hängt Körperkontakt fail-closed an Rust. Ist die Bibliothek nicht ladbar, fällt diese Kernfunktion aus. Die Paketprüfungen liefen nur auf Linux.
- **Der Grund war nicht erkennbar.** `_load()` verwarf den Ladertext (`except OSError: raise …("konnte nicht geladen werden")`).
- Mögliche Ursachen (UNKLAR, kein Gerät hier):
  - Linux-Paket auf dem Handy;
  - Paket in Download/sdcard (noexec);
  - die per Zig gebaute aarch64-Bibliothek passt nicht zu bionic.

## Ursache (geklärt durch deine Angabe: Pydroid 3, Ordner in Download)
Android lädt keinen nativen Code aus geteiltem Speicher (noexec). Hier nachgestellt mit einem noexec-tmpfs, `ctypes` meldet „failed to map segment from shared object“.
- **Stand 10 auf noexec:** Puppet-Schlag ergibt 503 `NATIVE_BOUNDARY_UNAVAILABLE`. Das ist identisch mit deinem Screenshot.
- **Stand 10a auf noexec:** Puppet-Schlag ergibt 200, F1 ist 12/12. Die Bibliothek wird byte-gleich (SHA-256 geprüft) aus dem privaten App-Speicher geladen (`native_boundary._app_kopie`).

Die erste falsche Stelle nach Kettenvertrag §6 liegt in Stand 06: Die Rust-Pflicht wurde eingeführt, ohne die Ladbarkeit auf der Laufzeitumgebung des Nutzers nachzuweisen.

## Änderung (Ebene 10a, fail-closed unverändert, keine Ersatzlogik nach Nutzerentscheidung 06a/M1)
- `matrix_api/native_boundary.py`:
  - `load_diagnosis` liest ELF-Kennung gegen Gerät, prüft noexec- oder sdcard-Ort und reicht den Ladertext wörtlich durch.
  - Der 503-Text nennt Grund und Abhilfe.
  - `status()` liefert den Ladezustand für Start und Health.
- `native_boundary._load`: Lädt der Paketort nicht, wird dieselbe Bibliothek aus einer byte-gleichen Kopie im App-Speicher geladen. Es gibt keine Ersatzlogik.
- `START.py`: Prüft den Kern einmal beim Start und schreibt `[RUST] … geladen` oder `[RUST-FEHLER] … Grund / Abhilfe`. Der Server startet trotzdem.
- `matrix_api/app.py`: `/api/health` hat das neue Feld `rustKern`.
- `src/components/shell.tsx`: Roter Balken oben auf jeder Seite mit Grund und Abhilfe, solange der Kern nicht geladen ist. Gleiches Muster wie der vorhandene Build-Hinweis.
- Paket:
  - neues Skript `RUST_AUF_DEM_HANDY_BAUEN.sh` (Termux: Rust installieren, Kern auf dem Gerät bauen, prüfen);
  - die Android-Anleitung nennt die zwei häufigsten Ursachen ganz oben.

## Nachweis
- `tests/test_rust_diagnose_10a.py`: 4/4 auf 10a, 4/4 rot auf 10.
- Paketprüfung 9d: Das Paket liegt auf einem noexec-Speicher, F1 läuft über den echten Weg (12/12), und Rust kommt aus der App-Kopie.
- Paketprüfung 9a2 (Start meldet „geladen“, Health ok) und 9c (fremde aarch64-Bibliothek auf x86-64: Grund beim Start, in Health und im 503).

## Weiter offen
Ob die mitgelieferte aarch64-Bibliothek auf deinem Gerät lädt, zeigt jetzt der Start selbst. Wenn nicht, behebt `RUST_AUF_DEM_HANDY_BAUEN.sh` die Ursache „Bibliothek passt nicht zu bionic“ auf dem Gerät.
