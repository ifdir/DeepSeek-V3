# Kettenvertrag §6: Gleichstand P25 → 10A, gemessen mit deinen echten Handy-Eingaben

**§6.1 Basis eingefroren:**
- `MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107.zip`, SHA-256 `33a51497…860d1`, 2 156 563 Byte, 273 Dateien.
- Verglichen mit Paket 10A `663eaaf` (Linux).

**§6.2/6.4 Gerätebeleg:** dein zurückgeschicktes 10A-Paket, Pydroid 3, Ordner in Download, Live-Log 08.11. 18:29–18:38 (`evidence/gleichstand_p25_10a/geraet_20261108/`). Die Geräte-Datenbank ist nicht im Repo, weil sie den API-Schlüssel enthalten kann.

**Messweg:**
- START.py und die Routen wie die UI: Puppet → Reaktionszug Mara → Commit; Neustart vor Eingabe 4.
- Die 5 Eingaben und **die echten Modellantworten vom Gerät** als Drehbuch (`tools/drehbuch_geraet_10a.json`).
- 1,5 s Modellzeit je Aufruf.
- Werkzeug: `tools/gleichstand_p25_10a.py`.

## Ergebnis je Fehlerbild

| Fehlerbild | Gerät 10A | P25 (Messung) | 10A (Messung) | Einordnung |
|---|---|---|---|---|
| Berührungs-Eingabe | 5/5 übernommen, kein 503 | 5/5 | 5/5 | Der Ausfall aus Stand 10 (Rust nicht ladbar aus Download) ist **auf dem Gerät behoben**. |
| Modellaufrufe je Austausch | – | 9 / 11 / 11 / 15 / 12 | 9 / 11 / 11 / 15 / 12 | **gleich** |
| Dauer je Austausch | 42–49 s | 12,2 / 12,2 / 12,3 / 18,4 / 13,9 s | 12,2 / 12,3 / 12,3 / 18,4 / 14,0 s | **gleich**. Ursache sind 8–12 Modell-Lesungen, die **nacheinander** laufen: Planer → Vollzug → Körper → Bewertung (parallel je Figur) → Kausalprüfung → Formulierung → Bewegung → Körper → Grenze. Das ist P25-Bestand, über SPS V65J/V65P/V65Q/V84/V92 gewachsen; V62 hatte 3 Stufen mit 7–15 s. |
| Maras Zustand über die Züge und nach dem Neustart | Furcht 0,73 → 0,845, Absicht „zurückziehen“ | Furcht 0,73 → 0,823 | identisch | **gleich**. Der Zustand wird genutzt und wirkt fort. |
| Wiederholung („Lass das … Ich hab Arbeit“, „Schritt zurück“) | ja | Brief an Mara | **Wort für Wort derselbe Brief**, Lesezustand und Systemtext in allen 5 Zügen | **P25-Bestand**, nicht durch 06–10A verursacht. AMASTER §51.3 (Finalizer „prüft … Wiederholung“) und §28 Schritt 19 sind in P25 nicht umgesetzt (Finalizer = nur `_clean_speech`, `llm_contract.py:170`; Gesamtkarte K-13 ROT). Die SPS-Lösung V65.6 („← dein letzter Beitrag: nur Anschluss, nicht wiederholen“) ist in P25 und 10A vorhanden und steht im Geräte-Prompt. „Ich hab Arbeit“ ist eine typische Wendung aus Maras Profil, „tritt zurück“ ist ihr Kompass-Merkmal „Gewalt: sichtbar“ (SPS Z. 3215 kennt diese Wiederholung). |
| AutoChat nur über den Browser | – | `chat.$sessionId.tsx` `queueAuto` | gleich | **P25-Bestand** (Gesamtkarte K-05). |
| Einziger Unterschied P25 → 10A in den Modellaufrufen | | | `beziehung_zum_handelnden` nennt jetzt Person und Ereignis | gewollte Korrektur B2 (Stand 09) |

## Schluss nach §6.5
Für die vier Fehlerbilder (Dauer, Wiederholung, Zustand, AutoChat) gibt es **keine falsche Naht in den Ebenen 06–10A**. Die Ausgabe ist in allen Messgrößen identisch mit der eingefrorenen Basis. Die einzige Regression der Rust-Umstellung war der Berührungs-Ausfall auf Android. Er ist in 10A behoben und mit deinem Gerätelog belegt.

Offene AMASTER-Ketten aus P25, nicht neu erfunden, nur zugeordnet:
- **§51.3 / §28 Schritt 19 (Finalizer, K-13):** Wiederholung.
- **§48 (AutoChat, K-05):** AutoChat läuft nur über den Browser.
- **Lesungsreihenfolge:** Dauer.
