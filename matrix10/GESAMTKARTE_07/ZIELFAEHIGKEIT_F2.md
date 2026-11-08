# Zielfähigkeit F2: Die Figur handelt nach dem Erlebnis aus ihrem eigenen Zustand weiter

**Quellen:**
- AMASTER §28 Schritt 16 („nächsten Sprecher bestimmen“), §27.8, §47, §48, §68 Nr. 67
- Kettenvertrag §12.5 und §12.6
- SPS V61 (Fate über den Orchestrator), V65E (Sprecherwahl aus dem zuletzt committeten Ereignis)
- Gesamtkarte K-05

**Fähigkeit (SOLL):** Nach F1 (Johann schlägt Mara) passiert Folgendes ohne Nutzereingabe:
- Der Server wählt, wer reagiert, und zwar aus dem gespeicherten Zustand: Betroffenheit, Druck, Absicht.
- Genau diese Figur spricht oder handelt im Folgezug.
- Ihre Absicht („Abstand zu Johann halten“) zeigt sich als gültige Handlung („tritt zurück“ = entfernung).
- „Figuren weiterreden lassen“ (AutoChat) setzt das fort, auch nach einem Neustart.

| # | Glied | Kette | IST (gemessen, Stand 09) | Stand 10 |
|---|---|---|---|---|
| 1 | Der Server wählt nach der Tat die Betroffene; Begründung aus Zustand („vom letzten Ereignis betroffen“, „Druck 0.50 (Angst)“) | K-05 | erfüllt | erfüllt |
| 2 | Reaktionszug der Betroffenen wird committet | K-01/K-05 | erfüllt | erfüllt |
| 3 | Absicht → Handlung „entfernung“ wird validiert (Bewegungslesung) | K-03/K-05 | erfüllt (mit Testmodell) | erfüllt |
| 4 | **Der Folgezug ohne Eingabe spricht nur die vom Server gewählte Figur** | K-05 / K-01(c) | **ROT**: Gate wählt Johann, Client schickt Gustav, 200/200/200 | **erfüllt**: 409 `AUTOCHAT_SPRECHER_NICHT_GEWAEHLT`, nichts gespeichert |
| 5 | Gate-Sprecher spricht, auch nach Neustart | K-05/K-11 | erfüllt | erfüllt |
| 6 | Sprecherwahl ohne Wortlisten (Kandidatengründe enthalten „betrifft sie (n Treffer)“, „Synapse Gewalt“, „angesprochen“ per Namenstreffer) | K-05 | **ROT** | **ROT**, nicht angefasst: großer Umbau von `rank_speakers`, eigene Kette |
| 7 | AutoChat läuft serverseitig weiter (heute stößt nur der Browser an) | K-05 | ROT | ROT, nicht angefasst |
