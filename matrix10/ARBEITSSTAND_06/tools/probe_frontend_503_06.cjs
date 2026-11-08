// Arbeitsstand 06, K2 Frontend: echte gebaute P25-UI (START.py, frontend_dist) im Chromium.
// Bedienhandlungen ohne LLM, die den Rust-Einwilligungskern erreichen:
//   U1 "Öffnen" der Session "Fall 06"   -> GET /api/sessions/ses_v92
//   U2 "Chat-Reset" der Session "Fall 06" (Schreibhandlung)
// Gemessen: API-Antworten der Handlung, sichtbarer Text im Hauptbereich, Screenshot.
// Aufruf: node probe_frontend_503_06.cjs <variante> <ausgabe.json> <screenshot-praefix>
const { chromium } = require('playwright');
const fs = require('fs');
const [variante, out, shot] = process.argv.slice(2);
const UI = 'http://127.0.0.1:8180';

async function handlung(p, name, fn) {
  const api = [];
  const onResp = async (r) => {
    if (!r.url().includes('/api/') || r.url().includes('/api/health')) return;
    let body = null; try { body = await r.json(); } catch (e) {}
    api.push({ status: r.status(), method: r.request().method(), url: r.url().replace(UI, ''),
               code: body && (body.code || body.error) || null, ok: body ? body.ok : null });
  };
  const dialoge = [];
  const onDialog = async (d) => { dialoge.push(d.type() + ': ' + d.message().slice(0, 160)); await d.accept(); };
  p.on('response', onResp); p.on('dialog', onDialog);
  await fn(); await p.waitForTimeout(2500);
  p.off('response', onResp); p.off('dialog', onDialog);
  const main = await p.$('main') ? await p.innerText('main') : await p.innerText('body');
  const alerts = await p.$$eval('[role=alert],[role=status],[aria-live]', els => els.map(e => e.innerText.trim()).filter(Boolean));
  await p.screenshot({ path: `${shot}_${name}.png`, fullPage: false });
  const text = main.replace(/\s+/g, ' ');
  return { handlung: name, api, dialoge, sichtbar_alerts: alerts,
           sichtbar_fehler: /503|NATIVE_BOUNDARY_UNAVAILABLE|NATIVE_ABI_MISMATCH|Rust-Schreibgrenze/.test(text + ' ' + alerts.join(' ')),
           text_auszug: text.slice(0, 900) };
}

(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1300, height: 1000 } });
  await p.goto(UI + '/user', { waitUntil: 'networkidle' });
  const erg = [];
  // U0: Nutzer "admin" waehlen (laedt /api/mcc) - Ergebnis auf DERSELBEN Seite, ohne Neuladen (Speicherzustand bleibt)
  erg.push(await handlung(p, 'U0_nutzer_waehlen', async () => { await p.getByRole('button', { name: 'Wählen' }).first().click(); }));
  // weiter nur per In-App-Navigation (Link "Chat"), wie ein Nutzer
  erg.push(await handlung(p, 'U0b_chat_seite', async () => { await p.getByRole('link', { name: 'Chat', exact: true }).first().click(); }));
  const karte = () => p.locator('text=Fall 06').filter({ hasNotText: 'Avatar' }).first().locator('xpath=ancestor::*[.//button[normalize-space()="Öffnen"]][1]');
  const bedienbar = async () => (await karte().getByRole('button', { name: 'Öffnen' }).count()) > 0;
  if (await bedienbar()) {
    erg.push(await handlung(p, 'U2_chat_reset', async () => { await karte().getByRole('button', { name: 'Chat-Reset' }).click(); }));
    erg.push(await handlung(p, 'U1_oeffnen', async () => { await karte().getByRole('button', { name: 'Öffnen' }).click(); }));
  } else {
    for (const n of ['U2_chat_reset', 'U1_oeffnen']) erg.push({ handlung: n, nicht_bedienbar: 'Session-Liste nicht geladen (keine Karte "Fall 06" sichtbar)' });
  }
  fs.writeFileSync(out, JSON.stringify({ variante, handlungen: erg }, null, 2));
  for (const e of erg) console.log(variante, e.handlung, e.nicht_bedienbar ? ('NICHT BEDIENBAR: ' + e.nicht_bedienbar) :
    (JSON.stringify(e.api.map(a => `${a.status} ${a.method} ${a.url} ${a.code || ''}`)) + ' fehler_sichtbar=' + e.sichtbar_fehler +
     ' alerts=' + JSON.stringify(e.sichtbar_alerts).slice(0, 220)));
  await b.close();
})();
