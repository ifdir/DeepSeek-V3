# Prüfmaschine V1.2 gegen AMASTERv2 – Konformitätsprüfung

**Stand:** 7. November 2026
**Gegenstand:** `MATRIX10_PRUEFMASCHINE_V12_20261107.zip`, SHA-256 `5ba3350f66797f9e1956bbb831cae0d002f365421fd0c5347bc5ab03ed4d769e`. Die ZIP-Integrität ist geprüft (PASS).
**Maßstab:** AMASTERv2 (§1–§70), Matrix10.txt und der Kettenvertrag. Alle drei sind vollständig gelesen.

## STATUS

| Gegenstand | Status |
| --- | --- |
| Quellenbindung der Maschine | **ROT** |
| Fallkatalog (10 Fälle) gegen AMASTERv2 | **TEILGESCHLOSSEN**: 6 konform, 3 überstreng, 1 widerspricht AMASTER |
| Abdeckung des AMASTER | **ROT**: 4 von 16 Achsen mit Fällen; die Einwilligungs- und Lifecycle-Kette hat 0 Fälle |
| Interne Integrität (Manifest) | 18/18 Hashes stimmen mit `ABNAHME_V12.json` |
| Selbstabnahme 109/109 | **NICHT_PRÜFBAR** hier, weil P23-, P24- und P25-ZIP, Original-DB, Node und Modell fehlen; nur als Beleg gelesen |
| Anwendbarkeit auf den Rust-Stand 05 | **NICHT_PRÜFBAR**: Es gibt kein lauffähiges Produkt-ZIP, und die Einwilligungskette hat in V12 keinen Fall |

**Ergebnis:** Eine bestandene V12 belegt **keine** AMASTER-Konformität. Das ist kein Formfehler. Die Maschine prüft gegen eine andere Sollquelle, und ihre Fälle decken den AMASTER nur zu einem kleinen Teil ab.

## GELESEN

- `README_ZUERST_LESEN.txt`, `ABNAHME_V12.json`, `PRUEFREGELN_V12.json`, `NACHTRAG_01_SOLLQUELLEN_ENTWURF.txt`, `V92_PRUEFMASCHINE_V12_BERICHT_20261107.md`.
- `kettenpruefer/kp_faelle.json` (alle 10 Fälle).
- `kettenpruefer/kettenpruefer.py`: die Prüfung von Glied 5, 6, 9 und 10, insbesondere `keine_wirkung` und `nicht`.
- `BELEGE_20261107/HASHES.txt`.
- Sollquellen: `AMASTERv2.md(1).txt` (§1–§70), `Matrix10.txt` (vollständig), `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` (§0–§6, §16, §17).

## FEHLT

- `2_7master.txt` (`095d4554…`). Gegen diese Datei prüft V12. Sie liegt nicht vor; ich kann also nicht prüfen, wie sie sich zum AMASTERv2 verhält.
- Die SPS-Fassung `1f0cb05d…`, gegen die V12 prüft. Vorhanden ist nur `6c1747bb…`.
- Die P22- bis P25-ZIPs, die Original-DB `e03dc445…` und die Test-EPUB.

---

## 1. Quellenbindung: ROT

| | Kettenvertrag §0 (verbindlich) | V12 `PRUEFREGELN_V12.json` |
| --- | --- | --- |
| Architekturmaster | `AMASTERv2.md(1).txt` `fb4f2015…` | `2_7master.txt` `095d4554…` |
| Produkt-/Kausalfluss | `Matrix10.txt` `1465980a…` | **fehlt** |
| SPS | – | `1f0cb05d…` |
| Kettenvertrag | `e62cf6bc…` | `e62cf6bc…` (identisch) |

- V12 begründet die Abweichung so: Die §0-Dateien lägen „in keinem Paket seit P22 und in keinem Upload“ vor (Nachtrag 01, Punkt 1). **Das stimmt nicht mehr.** Beide liegen im Rust-Arbeitsstand 04 unter `sources/` und haben **exakt die §0-Hashes** (`fb4f2015…`, `1465980a…`).
- Der Nachtrag sagt selbst (Punkt 3): *„Taucht eine der beiden §0-Dateien wieder auf, wird sie gegen ihren Hash geprüft und hat Vorrang.“* Damit ist die Sollquelle der V12 ab sofort überholt.
- **Belegte Abweichung zwischen 2_7master und AMASTERv2:** V12 und das SPS zitieren `§36.5` (Gültigkeitsfenster der Einwilligung) und `§46.6`. Beide Abschnitte gibt es im AMASTERv2 nicht: §36 endet mit 36.4, §46 mit 46.3. Die beiden Dokumente sind also nachweislich verschieden.
- Matrix10.txt prüft V12 gar nicht. Seine drei Präzisierungen haben in V12 keinen einzigen Fall:
  - vollständig befüllte Profile mit gekennzeichneter Ableitung,
  - psychologische Wirkung neuen Wissens,
  - Fate sucht weltlogische Wege zum Storyziel, ohne den Avatar zu steuern.
- Kettenvertrag §2 verlangt: *„Auch die Prüfmaschine selbst ist zu prüfen.“* Diese Prüfung ist hiermit erfolgt, mit Ergebnis ROT bei der Quellenbindung.

## 2. Die 10 Fälle gegen AMASTERv2

| Fall | V12-SOLL | AMASTERv2 | Urteil |
| --- | --- | --- | --- |
| PU1 eigene Handlung | gespeichert mit Figuren-ID, Anwesende sind Zeugen, Folgezug erhält das Ereignis | §27.4, §26, §4, §68 Nr. 27 | **konform** |
| PU2 Anrede gegen UI-Auswahl | Angesprochener im Text gilt vor der UI-Auswahl | §25 nennt Namensnennung, UI-Auswahl usw. **ohne Rangfolge** | konform als Auslegung; die Rangfolge ist abgeleitet, nicht AMASTER-Text |
| PU3 fremde Rede im Puppet | 422, **nichts gespeichert** (keine Fakten, Züge oder Commits) | §34.1: Eine nicht validierte Komponente *darf* „als sichtbare oder unbestätigte Redeprovenienz erhalten bleiben“, nur ohne Wirkung | **überstreng**: AMASTER-konforme Provenienz ergibt in V12 ROT |
| PU4 verneinte Handlung + Rede | kein Kuss, „Hallo“ wird gespeichert | §34.1, §68 Nr. 32/33 | **konform** |
| AV1 Avatar fragt | Rede des Avatars an Mara; Mara antwortet | §27.3, §25; §28 erlaubt „mögliche Unterbrechung, kontrollierte Variation“ | konform; „antwort_von M“ ist enger als §28 |
| AV2 fremde Rede im Avatar | 422, nichts gespeichert | §27.3; zur Provenienz siehe PU3 | **überstreng** wie PU3 |
| GO1 God: bewusstlos | Körper gesetzt, Mara spricht nicht und nimmt nicht wahr; Glied 13 „Soll offen“ | §46.1, §43, §26, §20 | konform. **Glied 13 ist aus AMASTERv2 entscheidbar**, siehe 2.1 |
| GO2 God: „nicht bewusstlos“ | **kein body_state-Fakt** für Mara erlaubt; „verneinter Zustand ändert nichts“ | §27.6/§46.1: God setzt bindende Zustandsfakten, „werden kanonisch gespeichert“ | **widerspricht**, siehe 2.2 |
| RE1 Regie: Gustav geht in die Küche | Actor gebunden, nur Gustav wechselt den Ort | §27.5, §46.2, §20, §26 | **konform** |
| RE2 Regie: unbekannte Figur | 422, keine neue Figur | §27.5, §46.2, §13 (eine Figur entsteht nur über Spawn/Erstellung mit Vorschau) | konform in der Sache; zur Provenienz siehe PU3 |

### 2.1 GO1 Glied 13 – entscheidbar, nicht „Soll offen“

V12 lässt offen, ob Anwesende den von God gesetzten Zustand wahrnehmen. Begründung der V12: 2_7master nennt „God setzt Wissen“ nur für Betroffene. Im AMASTERv2 ist das **keine God-Wissensfrage, sondern eine Wahrnehmungsfrage**:
- §46.1: God setzt den körperlichen Zustand; die Wirkung geht „in die zuständigen kanonischen Schichten“, also PhysicalState und SceneState.
- §20: SceneState führt Körperpositionen und die sichtbare Reichweite.
- §26: Wissen entsteht über einen gültigen Weg, darunter **„gesehen“**.
- §39 trennt objektive Wahrheit und Figurenwissen.

**SOLL nach AMASTERv2:** Anwesende, sehfähige Figuren erhalten über den Weg *gesehen* das Wissen um den sichtbaren Zustand („Mara liegt bewusstlos da“). Mara selbst erhält nichts (sie nimmt nicht wahr, §43). Abwesende erhalten nichts. Den God-Akt selbst kennt niemand. Eine Bestätigung durch den Vertragseigner ist nicht nötig; der AMASTER entscheidet das.

### 2.2 GO2 – Fallerwartung widerspricht AMASTER

- Die V12 erwartet `nicht: [{kind: body_state, akteur: M}]` und begründet: „Ein verneinter Zustand ändert den Körper nicht.“
- Nach §27.6 und §46.1 ist „Mara ist nicht bewusstlos“ eine klare, bindende God-Tatsache; God-Fakten „werden kanonisch gespeichert“. Eine Verneinung ist keine Unklarheit (§24: „Unklare Korrekturen …“).
- Wäre Mara vorher bewusstlos, **müsste** derselbe Satz sie wecken. Die V12 hat für diesen Fall keine Prüfung, und ihre Begründung würde ihn verbieten.
- In der Ausgangslage (Mara ist wach) ändert sich nichts. Ein Produkt, das die God-Tatsache trotzdem korrekt als body_state speichert, bekommt aber **falsches ROT**.
- Nötig sind GO2-neu (Speichern zulässig, `canSpeak` bleibt true) und **GO3** (Mara ist bewusstlos → God: „Mara ist nicht bewusstlos“ → wach, spricht im Folgezug).

## 3. Abdeckung: welche AMASTER-Teile V12 nicht prüft

Die V12-Achsen folgen den Pflichtketten §5 und §7–§15 des Kettenvertrags. Fälle gibt es nur für Avatar, Puppet, Regie und God. Ohne jeden Fall sind:

| AMASTER-Bereich | Inhalt | Bezug zu V12 |
| --- | --- | --- |
| **§35–§37, §68 Nr. 9 und 35** | Proposition, Goal, Lifecycle, Current State, Request/Refusal/Acceptance, Zeitfenster | **keine Achse**; Vorbefund E-1 „Einwilligungs-/Grenzenkette offen“ hat **0 Fälle** |
| §21 | Timeline: Filter, historische Evidenz vs. Current State | keine Achse |
| §15/§16 | Chathere-Kompass; keine SceneBehaviorEngine | allenfalls in §8 enthalten, 0 Fälle |
| §45 | Social/Synapsen als abgeleitete Werte | 0 Fälle |
| §49/§50/§51 | BrainContext, LLM-Grenze, Narrator/Finalizer | nur Glied 13 „erhalten“; die Verwendung ist laut V12 selbst „offen“ |
| §61/§62 | Accessibility, STT/TTS | keine Achse |
| §65/§67 | Diagnose/Logs, Sicherheit | keine Achse |
| Matrix10 Nr. 5, 16, 13 | Profil-Vollbefüllung mit Ableitungskennzeichnung, psychologische Wirkung, Fate-Rückführung | 0 Fälle |

**Wichtig für den Rust-Stand:** Der dort reparierte Bereich hat in V12 **keinen einzigen Fall**. Das betrifft die Einwilligungs-Current-State-Kette (C04, Tat-Antwort/Widerruf S05) und die Schreibgrenze für Lifecycle-Einträge (W1–W3). Ein V12-GRÜN würde diese Fehler nicht finden.

## 4. Was nötig ist (nicht in diese Maschine eingreifen)

Nach den V12-Regeln ist jede Regel- oder Falländerung eine **neue Maschinenversion mit eigener Selbstabnahme**. Ich habe die V12 deshalb **nicht verändert**.

Für eine V1.3, die dem AMASTER entspricht, sind nötig:

1. **Sollquellen** = `AMASTERv2.md(1).txt` (`fb4f2015…`) + `Matrix10.txt` (`1465980a…`) + Kettenvertrag (`e62cf6bc…`), wie §0 es verlangt. Damit ist Nachtrag 01 gegenstandslos, und alle Zeilenzitate im Fallkatalog müssen auf AMASTERv2 umgestellt werden.
2. **PU3/AV2/RE2:** „keine Wirkung“ statt „nichts gespeichert“. Erlaubt ist unbestätigte Provenienz ohne Wirkung, Zeugenwissen, Commit-Fortschritt oder Current-State-Änderung (§34.1).
3. **GO1 Glied 13:** Erwartung nach 2.1.
4. **GO2 neu fassen und GO3 ergänzen**, siehe 2.2.
5. **Neue Achse „Proposition/Lifecycle/Einwilligung“ (§35–§37)** mit Kettenfällen aus den belegten Defekten:
   - C04 fremder Giver;
   - C04 abgelaufene Zustimmung bzw. Ablehnung;
   - S05 Widerruf einer Ausnahme hebt die Ablehnung jeder Berührung nicht auf;
   - W1–W3 Schreibgrenze.
   Jeder Fall mit allen 20 Gliedern, inklusive Folgezug, Reload und Isolation.
6. Die 12 Achsen ohne Fälle bleiben UNGEPRÜFT, bis sie Fälle haben. Das hat die V12 selbst so festgelegt.
