# Matrix10 – Arbeitsstand 09, Testprodukt Linux x86_64 (ROT)

**Keine Produktfreigabe.** Startbares Testpaket zum Prüfen des erreichten Entwicklungsstands.

- **Inhalt:**
  - P25 mit den Reparaturen 06/06a (Rust-Einwilligungskern ABI 3), 07 (K-01 TurnTruth- und Commit-Bindung, W2, SEC) 08 (K-02 Wahrnehmung der Antwortphase, Figurenabruf) und 09 (F1-B2: Bewertung nennt die Person ihres Beziehungsrahmens);
  - fertig gebautes Frontend (`frontend_dist/`);
  - Rust-Bibliothek (`matrix_api/native/libmatrix_boundary_core.so`).
- **Plattform:** Dieses Paket gibt es als Linux x86_64 (geprüft) und als Android aarch64/Termux (gebaut, auf Android ungeprüft; Anleitung `MATRIX10_STAND09_START_ANDROID.txt`). Windows ist nicht geprüft.
- **Starten:** siehe `MATRIX10_STAND09_START.txt`. Kurz: `python3 -m pip install -r requirements.txt`, dann `python3 START.py`, dann im Browser http://127.0.0.1:8080 öffnen.
- **Status, Hashes und offene Punkte:** `MATRIX10_STAND09_STATUS.json`.
- **Vertragsgrundlage:** `vertrag/` (AMASTERv2, Matrix10.txt, Kettenvertrag) und `MATRIX10_SPS_MASTER.md`.
- **F1 (Erlebnis → Bedeutung → nächster Zug → Neustart):** Kernel-Kette mit lokalem Testmodell erfüllt. Die Bedeutung braucht ein Modell: ohne API-Schlüssel ändert ein Erlebnis Gefühl, Absicht und Beziehung nicht.
- **Herkunft:** Die frühere P25-Beschreibung steht unverändert in `README_P25_QUELLARBEITSKOPIE.md`.
