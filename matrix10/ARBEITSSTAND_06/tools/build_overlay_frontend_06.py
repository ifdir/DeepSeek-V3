#!/usr/bin/env python3
"""Stand 06a / M3 (vom Nutzer freigegeben: NUR api.ts und chat.index.tsx, NUR korrekte Fehleranzeige).

overlay/src/lib/matrix/api.ts     : apiGetMcc liest bei !r.ok Code und Meldung (wie apiJson) -> Fehler traegt den Code.
overlay/src/routes/chat.index.tsx : "Keine Session" nur nach ERFOLGREICHER Abfrage mit leerer Liste; bei Fehler
                                    (z. B. 503 NATIVE_BOUNDARY_UNAVAILABLE) eine sichtbare Fehlermeldung mit Code;
                                    Startleser-Fehler statt endlosem "Laedt...". Keine neue Route, kein neuer Store.
Aufruf: python3 -I build_overlay_frontend_06.py <P25-Produktordner> <overlay-ordner>
"""
import hashlib
import sys
from pathlib import Path

ORIG = {"src/lib/matrix/api.ts": "e6d31f9fd46615df354bb5f614ae6a0ed06ae62004814a2e6d0124b5853d4fc5",
        "src/routes/chat.index.tsx": "446627abfaa51f6d0f9e13fb17cc80c7f5a7a38e36294859386edecdbf6c1952"}


def main():
    p25, ov = Path(sys.argv[1]), Path(sys.argv[2])
    src = {}
    for rel, h in ORIG.items():
        t = (p25 / rel).read_text(encoding="utf-8")
        if hashlib.sha256(t.encode()).hexdigest() != h:
            raise SystemExit(f"{rel}: P25-Original hat nicht den erwarteten Hash")
        src[rel] = t

    def rep(rel, a, b):
        assert src[rel].count(a) == 1, (rel, a[:70])
        src[rel] = src[rel].replace(a, b)

    rep("src/lib/matrix/api.ts",
        '''  const r = await fetch("/api/mcc", { headers: { ...actorHeader(actor) } });
  if (!r.ok) throw new Error(`GET /api/mcc ${r.status}`);
  return r.json();''',
        '''  const r = await fetch("/api/mcc", { headers: { ...actorHeader(actor) } });
  if (!r.ok) {
    // Stand 06a (M3): keep the server's code and message readable, like apiJson - a 503 of the consent core is a
    // technical failure and must be shown as such, never as an empty data set.
    const data = (await r.json().catch(() => ({}))) as { error?: string; message?: string; code?: string };
    const code = data.code || data.error || "HTTP_ERROR";
    const reason = data.message && data.message !== code ? `${code}: ${data.message}` : code;
    throw Object.assign(new Error(`GET /api/mcc ${r.status} ${reason}`), { body: data, status: r.status });
  }
  return r.json();''')

    c = "src/routes/chat.index.tsx"
    rep(c, '''import { useState } from "react";''', '''import { useEffect, useState } from "react";''')
    rep(c, '''import { useHydrated } from "@/lib/matrix/use-hydrated";''',
        '''import { useHydrated, useMccReaderError } from "@/lib/matrix/use-hydrated";
import { apiGetMcc } from "@/lib/matrix/api";''')
    rep(c, '''  const hydrated = useHydrated();
  const activeUserId = useMatrix((s) => s.activeUserId);''',
        '''  const hydrated = useHydrated();
  const readerError = useMccReaderError();   // Stand 06a (M3): the existing start reader's failure
  const activeUserId = useMatrix((s) => s.activeUserId);''')
    rep(c, '''  const [importErr, setImportErr] = useState<string | null>(null);
''',
        '''  const [importErr, setImportErr] = useState<string | null>(null);
  // Stand 06a (M3, AMASTER §65 "Fehler duerfen nicht verschluckt werden"): an empty list is shown as "Keine Session"
  // only when the existing MCC reader CONFIRMS it; a failed read (e.g. 503 of the consent core) is a visible error.
  const [leer, setLeer] = useState<{ status: "offen" | "leer" | "fehler"; fehler?: string }>({ status: "offen" });
  useEffect(() => {
    if (!hydrated || !activeUserId || mine.length > 0) return;
    let aktiv = true;
    setLeer({ status: "offen" });
    apiGetMcc(activeUserId)
      .then((m) => {
        if (!aktiv) return;
        const eigene = ((m.sessions as { userId?: string }[] | undefined) ?? []).filter((x) => x.userId === activeUserId);
        setLeer(eigene.length === 0 ? { status: "leer" }
          : { status: "fehler", fehler: `${eigene.length} Session(s) auf dem Server, aber hier nicht geladen - Seite neu laden.` });
      })
      .catch((err) => {
        if (aktiv) setLeer({ status: "fehler", fehler: err instanceof Error ? err.message : String(err) });
      });
    return () => {
      aktiv = false;
    };
  }, [hydrated, activeUserId, mine.length]);
  const ladeFehler = readerError || (leer.status === "fehler" ? leer.fehler || "unbekannt" : null);
''')
    rep(c, '''  if (!hydrated) {
    return (
      <Shell title="Chat">
        <p className="text-sm text-muted">Lädt…</p>
      </Shell>
    );
  }''',
        '''  if (!hydrated) {
    return (
      <Shell title="Chat">
        {readerError ? (
          <p className="text-sm text-danger" role="alert" data-testid="sessions-load-error">
            Sessions konnten nicht geladen werden – technischer Fehler, keine leere Liste: {readerError}
          </p>
        ) : (
          <p className="text-sm text-muted">Lädt…</p>
        )}
      </Shell>
    );
  }''')
    rep(c, '''        {mine.length === 0 ? <Empty>Keine Session. Unten anlegen — Welt muss ausdrücklich gewählt werden.</Empty> : null}''',
        '''        {ladeFehler ? (
          <p className="mb-2 text-sm text-danger" role="alert" data-testid="sessions-load-error">
            Sessions konnten nicht geladen werden – technischer Fehler, keine leere Liste: {ladeFehler}
          </p>
        ) : mine.length === 0 ? (
          leer.status === "leer" || !activeUserId ? (
            <Empty>Keine Session. Unten anlegen — Welt muss ausdrücklich gewählt werden.</Empty>
          ) : (
            <p className="text-sm text-muted">Sessions werden geprüft…</p>
          )
        ) : null}''')
    for rel, t in src.items():
        out = ov / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(t, encoding="utf-8")
    print("overlay api.ts + chat.index.tsx geschrieben")


if __name__ == "__main__":
    main()
