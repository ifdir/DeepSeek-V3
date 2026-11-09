# Matrix10 – Arbeitsstand 08, Testprodukt Linux x86_64 (ROT)

**Keine Produktfreigabe.** Startbares Testpaket zum Prüfen des erreichten Entwicklungsstands.

- **Inhalt:**
  - P25 mit den Reparaturen 06/06a (Rust-Einwilligungskern ABI 3), 07 (K-01 TurnTruth- und Commit-Bindung, W2, SEC) und 08 (K-02 Wahrnehmung der Antwortphase, Figurenabruf);
  - fertig gebautes Frontend (`frontend_dist/`);
  - Rust-Bibliothek (`matrix_api/native/libmatrix_boundary_core.so`).
- **Plattform:** nur Linux x86_64 geprüft. Windows und Android sind nicht geprüft.
- **Starten:** siehe `MATRIX10_STAND08_START.txt`. Kurz: `python3 -m pip install -r requirements.txt`, dann `python3 START.py`, dann im Browser http://127.0.0.1:8080 öffnen.
- **Status, Hashes und offene Punkte:** `MATRIX10_STAND08_STATUS.json`.
- **Vertragsgrundlage:** `vertrag/` (AMASTERv2, Matrix10.txt, Kettenvertrag) und `MATRIX10_SPS_MASTER.md`.
- **Herkunft:** Die frühere P25-Beschreibung steht unverändert in `README_P25_QUELLARBEITSKOPIE.md`.
