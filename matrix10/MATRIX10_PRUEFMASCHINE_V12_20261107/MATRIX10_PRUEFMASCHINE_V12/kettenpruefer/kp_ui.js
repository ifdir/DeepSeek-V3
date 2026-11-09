// Kettenprüfer V1.2: Bedienung der ECHTEN Matrix10-Oberfläche (Playwright, Chromium).
// Eingabe: JSON-Datei mit dem Fall. Ausgabe: JSON auf stdout (letzte Zeile).
// Der Treiber schreibt nichts selbst in die Datenbank und erfindet keine Wirkung;
// er bedient nur die Oberfläche und schneidet mit, was Browser und Server austauschen.
// V1.2: Sichtprüfung nur im Gesprächsverlauf (ARIA role="log"), nicht auf der ganzen Seite
// (Seitenleisten nennen Orte und Sitzungsnamen); Modus "ansehen" für die Rückanzeige nach dem Server-Neustart.
const fs = require('fs');
const { chromium } = require(process.env.KP_PLAYWRIGHT || 'playwright');

const fall = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const UI = fall.ui || 'http://127.0.0.1:8080';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const MODUS_REITER = { puppet: 'Puppet', avatar: 'Avatar', gott: 'Gott', regie: 'Regisseur' };
const ROUTE = { puppet: '/api/kernel/puppet', avatar: '/api/kernel/prepare', gott: '/api/kernel/god', regie: '/api/kernel/regie' };
const norm = (t) => String(t || '').replace(/\s+/g, ' ').trim();

async function verlauf(p) {
  const log = p.locator('[role="log"]');
  if ((await log.count()) !== 1) return null;   // kein eindeutiger Gesprächsverlauf: nicht prüfbar
  return norm(await log.innerText());
}
async function meldungen(p) {
  const a = await p.locator('[role="alert"]').allInnerTexts();
  const s = await p.locator('[role="status"]').allInnerTexts();
  return a.concat(s).map((t) => norm(t).slice(0, 300)).filter(Boolean);
}

(async () => {
  const out = { fall: fall.id, schritte: [], anfragen: [], antworten: [] };
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1100, height: 1400 } });
  const wichtig = (u) => /\/api\/(kernel|llm\/formulate)/.test(u);
  p.on('request', (q) => {
    const u = q.url();
    if (!wichtig(u) || q.method() !== 'POST') return;
    let body = {};
    try { body = JSON.parse(q.postData() || '{}'); } catch (e) { }
    const t = body.truth || {};
    out.anfragen.push({
      pfad: new URL(u).pathname,
      // §16 Glied 04: gesendete IDs, Rolle, Modus, Akteur, Ziel, Scope, Autorität
      sessionId: body.sessionId || (body.session || {}).id || null,
      figur: (body.figure || {}).id || (body.speaker || {}).id || null,
      ziel: body.targetId || t.targetId || t.target_id || null,
      rolle: t.role || body.role || null, autoritaet: t.authority || null, sprichtAls: t.speakAs || null,
      scope: body.scope || null, text: body.text || t.text || null,
      wiederaufnahme: !!body.resumePending,
    });
  });
  p.on('response', async (r) => {
    const u = r.url();
    if (!wichtig(u) || r.request().method() !== 'POST') return;
    let j = {};
    try { j = await r.json(); } catch (e) { }
    out.antworten.push({ pfad: new URL(u).pathname, status: r.status(), code: j.code || null, meldung: String(j.message || '').slice(0, 300) });
  });
  const schritt = (s) => out.schritte.push(s);

  await p.goto(UI + '/user'); await sleep(1500);
  await p.getByRole('button', { name: 'Wählen' }).first().click(); await sleep(1000);
  await p.goto(UI + '/chat/' + fall.sessionId); await sleep(3500);
  schritt('Profil gewählt, Chat ' + fall.sessionId + ' geöffnet');

  if (fall.nurAnsehen) {
    // §16 Glied 16: Rückanzeige aus dem gespeicherten Zustand nach dem Server-Neustart
    out.verlauf_nach_neustart = await verlauf(p);
    await p.screenshot({ path: fall.bild + '_nach_neustart.png', fullPage: true });
    schritt('nach Server-Neustart angesehen');
    await b.close();
    console.log(JSON.stringify(out));
    return;
  }

  if (fall.modus === 'puppet') {
    await p.getByLabel('Spreche als').selectOption('char:' + fall.figur);
    schritt('Spreche als: Puppet ' + fall.figur);
  } else {
    await p.getByRole('button', { name: MODUS_REITER[fall.modus], exact: true }).click();
    schritt('Modus-Reiter: ' + MODUS_REITER[fall.modus]);
    if (fall.modus === 'avatar') { await p.getByLabel('Spreche als').selectOption('avatar'); schritt('Spreche als: Avatar'); }
  }
  await sleep(1200);
  if (fall.ziel) { await p.getByLabel(/Direktes Ziel/).selectOption(fall.ziel); schritt('Direktes Ziel: ' + fall.ziel); await sleep(600); }
  await p.getByRole('textbox', { name: 'Chat-Eingabe' }).fill(fall.text);
  const haupt = p.waitForResponse((x) => x.url().includes(ROUTE[fall.modus]) && x.request().method() === 'POST', { timeout: 200000 });
  await p.getByRole('button', { name: 'Senden' }).click();
  schritt('Senden: ' + fall.text);
  try { const r = await haupt; out.hauptstatus = r.status(); } catch (e) { out.hauptstatus = 'zeitgrenze'; }
  // Startet die Oberfläche nach der Hauptantwort KEINEN weiteren Kernel-/Modellaufruf, gibt es keinen Folgezug
  // (dann nicht 200 s warten). Erkennung allgemein über die Aufrufe, nicht über Meldungstexte.
  if (out.hauptstatus === 200) {
    const commit = p.waitForResponse((x) => x.url().includes('/api/kernel/commit') && x.request().method() === 'POST', { timeout: 200000 })
      .then(() => true, () => false);
    const hauptIdx = out.anfragen.findIndex((a) => a.pfad === ROUTE[fall.modus]);
    const start = Date.now();
    while (out.anfragen.length <= hauptIdx + 1 && Date.now() - start < 20000) await sleep(500);
    if (out.anfragen.length <= hauptIdx + 1) { out.folgezug_commit = false; out.folgezug_hinweis = 'kein Folgezug-Aufruf binnen 20 s nach der Hauptantwort'; }
    else out.folgezug_commit = await commit;
  }
  await sleep(4000);
  out.meldungen = await meldungen(p);
  out.verlauf_vor_reload = await verlauf(p);
  await p.screenshot({ path: fall.bild + '_nach_senden.png', fullPage: true });
  // §16 Glied 17: Neuladen und sichtbare Rückanzeige aus dem gespeicherten Zustand
  await p.reload(); await sleep(4000);
  out.verlauf_nach_reload = await verlauf(p);
  await p.screenshot({ path: fall.bild + '_nach_reload.png', fullPage: true });
  schritt('Seite neu geladen');
  await b.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ fall: fall.id, fehler: String(e && e.message || e) })); process.exit(1); });
