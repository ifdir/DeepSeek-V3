# Zielfähigkeit F1: Was am Ende auf dem Handy funktionieren muss

**Quellen (gelesen):**
- AMASTERv2 §28 (Turnablauf, 23 Schritte), §35, §38–§44, §49, §68 Nr. 6–12
- Matrix10.txt Nr. 14–17, 20, 24
- SPS V62 („Wirkungskette Ereignis → Erleben → Zustand → Zeit“)
- Gesamtkarte 07/08 (K-01 bis K-13)
- Code Stand 08: `app.py:_appraise_perceived`, `llm_contract.appraise_events`, `kernel.apply_appraisals`

**Maßstab (Matrix10 Nr. 24):** Fertig ist F1 erst, wenn die ganze Kette läuft, nicht schon, wenn einzelne Tests grün sind. Ein Writer ist erst dann implementiert, wenn sein Ergebnis beim nächsten zuständigen Reader ankommt (Nr. 20).

## 1. Die Fähigkeit (SOLL, ein Durchlauf auf dem Handy)

> Session in der eingebauten Welt. Tom schlägt Mara. Mara ist verletzt, erschrickt, ihr Vertrauen zu Tom sinkt, sie will Abstand.
> Im nächsten Zug spricht Tom sie an: Mara antwortet misstrauisch, abweisend und mit Schmerz, nicht freundlich nach Profil.
> Nach dem Neustart der App ist das noch so.
> Clara war nicht dabei und weiß nichts davon.
> In einer neuen Session ist Mara wieder die aus dem Stamm.

| # | Glied | SOLL-Quelle | zuständige Kette | IST Stand 08 |
|---|---|---|---|---|
| 1 | Die Handlung „Tom schlägt Mara“ wird serverseitig gebunden: Actor Tom, Ziel Mara, Handlung (nicht nur Text) | §23, §25, §34.1 | K-01 | TEILGESCHLOSSEN |
| 2 | Wer sieht und hört es? Mara ja, Clara nein (abwesend) | §26, §39, §68 Nr. 6–7 | K-02 | TEILGESCHLOSSEN |
| 3 | Körperfolge: Verletzung und Schmerz begrenzen, was Mara kann | §43 | K-06 / Körper | UNKLAR: `classify_physical_effect` erkennt per Wortliste (`kernel.py:4544`) |
| 4 | **Bedeutung:** Der Schlag trifft Maras Kompass, Beziehung und Ziele. Daraus folgen Angst/Wut, weniger Vertrauen zu Tom und die Absicht „Abstand“ | Matrix10 Nr. 16–17, §42, §44, SPS V62.7 | **K-03** | **ROT:** Das Erleben ist laut SPS ein Modellvorschlag, den der Kernel prüft. **Ohne Provider läuft nur das Abklingen** (`app.py:_appraise_perceived`). Daneben gibt es zweite Schreiber per Wortliste (`apply_knowledge_effect` `kernel.py:2432`, `apply_synapses`-Rückfall) und die Socialseite überschreibt Beziehungen ohne Ereignis (`repos.py` Relation-Writer, `manuell`) |
| 5 | Erinnerung: Mara erinnert sich „Tom hat mich geschlagen“ (selbst erlebt, mit Quelle) | §38, §40 | K-02 | TEILGESCHLOSSEN. Epistemische Zustände (geglaubt, bezweifelt) fehlen: Z-14 |
| 6 | **Nächster Zug:** BrainContext enthält Schmerz, Gefühl, Beziehung zu Tom und die Erinnerung | §28 Schritte 10–13, §41, §49 | K-03 / K-02 | UNKLAR. `relationsHere` liegt im Spiegel (`kernel.py:14693`) und wird im Brief gelesen (`llm_contract.py:1868`). Ob der Wert aus Glied 4 dort ankommt, ist **nicht end-to-end gemessen** |
| 7 | Mara spricht aus diesem Zustand, nicht aus dem alten Profilbild | Matrix10 Nr. 18–19, §50 | K-13 / Provider | BLOCKIERT: Ohne Schlüssel gibt es keine echte Formulierung |
| 8 | Wer spricht als Nächstes, und reagiert Mara von selbst? | §28 Schritt 16, §48 | K-05 | ROT: Wortlisten-Ranking, AutoChat nur im Browser |
| 9 | Persistenz: Neustart, gleicher Zustand | §63 | K-11 | Live gehalten (L3) |
| 10 | Isolation: neue Session ohne das Erlebnis, Stamm unverändert | §18, §52, §68 Nr. 3 | K-11 / K-10 | Live gehalten (L4). Die Systemschleife schreibt jedoch in den Stamm: K-10 ROT |
| 11 | Läuft auf dem Gerät des Nutzers (Android/Termux, Rust-Kern lädt) | AMASTER §3 (lokal) | Plattform | Android-Paket gebaut, **auf Android ungetestet** |
| 12 | Modellzugang auf dem Gerät (Provider und Schlüssel gespeichert und benutzt) | §60, Matrix10 Nr. 1 | K-09 | Schlüsselleck geschlossen. Live-Provider BLOCKIERT |

## 2. Was das für die Reihenfolge heißt

- **K-03 ist der Kern von F1 und hängt am Modell.** Laut SPS V62 entsteht Bedeutung durch das Modell (Vorschlag), und der Kernel prüft und schreibt. Ohne Schlüssel kann F1 nie grün werden. Das hätte ganz am Anfang stehen müssen.
- **Die Kernel-Kette ist trotzdem ohne echtes Modell messbar.** Der Code kennt den Provider `custom` mit eigener Endpoint-URL (`llm_contract.py:2496`). Ein lokales, festes Test-Modell kann so über den **echten HTTP-Weg wie die Oberfläche** Bewertungen liefern. Dafür braucht es keine Produktänderung, keine neue Route und keine Testabkürzung im Kernel. Gemessen wird damit Glied 1 → 4 → 6 → 9 → 10, also wo die Kette bricht.
- **Echte Abnahme von F1 nur auf dem Handy mit echtem Schlüssel** (Glieder 7, 11, 12). Der Schlüssel wird dort unter „Konfiguration“ eingetragen, nicht im Chat.

## 3. Vorgehen (statt weiterer Einzelprüfungen)

1. **F1-Durchlauf** als ein Skript über HTTP, mit dem Test-Modell und Neustart. Das Ergebnis ist die erste Stelle, an der der Zustand aus Glied 4 nicht beim nächsten Reader ankommt.
2. **Nur dort reparieren**, über den vorhandenen Owner `apply_appraisals`. Zweite Schreiber (Wortlisten, Socialseite ohne Ereignis) werden nicht weiter gebaut, sondern nach Kettenvertrag §6 als Owner-Konflikt behandelt.
3. **Wiederholen, bis F1 mit dem Test-Modell durchläuft.** Danach folgen ein Paket für Linux und Android und deine Abnahme auf dem Handy mit echtem Modell.
4. Erst danach geht es um K-05: Mara handelt von selbst.
