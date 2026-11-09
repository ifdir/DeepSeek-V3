// Arbeitsstand 06 (K2) + 06a (M3): echte gebaute P25-UI (START.py, frontend_dist) im Chromium.
// Aufruf: node probe_frontend_503_06.cjs <variante ok|fehlt|abi2> <ausgabe.json> <screenshot-praefix>
//         [--storage-out <datei>]  (ok: gespeicherter Nutzer "admin" fuer den Neuladen-Fall)
//         [--storage-in <datei>]   (fehlt/abi2: Neuladen mit gespeichertem Nutzer)
// Handlungen: U0 Nutzer waehlen, U0b Chat-Seite (In-App), U2 Chat-Reset, U1 Session oeffnen,
//             U3 Neuladen mit gespeichertem Nutzer (nur Ausfall), U4 Nutzer ohne Session (nur ok).
// Kriterien M3: Ausfall -> sichtbare Fehlermeldung MIT Code, "Keine Session" NICHT sichtbar, kein Dauer-"Laedt...";
//               erfolgreich leere Liste -> "Keine Session" sichtbar.
const { chromium } = require('playwright');
const fs = require('fs');
const args = process.argv.slice(2);
const [variante, out, shot] = args;
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : null; };
const UI = 'http://127.0.0.1:8180';
const CODE = { fehlt: 'NATIVE_BOUNDARY_UNAVAILABLE', abi2: 'NATIVE_ABI_MISMATCH' }[variante] || null;

async function zustand(p) {
  const body = (await p.innerText('body')).replace(/\s+/g, ' ');
  const fehlerEl = p.locator('[data-testid="sessions-load-error"]');
  const fehlerText = (await fehlerEl.count()) ? (await fehlerEl.first().innerText()).replace(/\s+/g, ' ') : null;
  const alerts = await p.$$eval('[role=alert]', els => els.map(e => e.innerText.replace(/\s+/g, ' ').trim()).filter(Boolean));
  return {
    sessions_ladefehler: fehlerText,
    ladefehler_mit_code: !!(fehlerText && CODE && fehlerText.includes(CODE)),
    keine_session_sichtbar: body.includes('Keine Session'),
    laedt_sichtbar: /Lädt…/.test(body),
    fall06_karte_sichtbar: (await p.locator('text=Fall 06').count()) > 0,
    alerts,
    alert_mit_code: !!(CODE && alerts.some(a => a.includes(CODE))),
  };
}

async function handlung(p, name, fn) {
  const api = [];
  const onResp = async (r) => {
    if (!r.url().includes('/api/') || r.url().includes('/api/health')) return;
    let body = null; try { body = await r.json(); } catch (e) {}
    api.push({ status: r.status(), method: r.request().method(), url: r.url().replace(UI, ''),
               code: body && (body.code || body.error) || null, ok: body ? body.ok : null });
  };
  const onDialog = async (d) => { await d.accept(); };
  p.on('response', onResp); p.on('dialog', onDialog);
  await fn(); await p.waitForTimeout(3000);
  p.off('response', onResp); p.off('dialog', onDialog);
  await p.screenshot({ path: `${shot}_${name}.png`, fullPage: false });
  const z = await zustand(p);
  return { handlung: name, api, ...z, sichtbar_fehler: !!(z.sessions_ladefehler || z.alerts.length) };
}

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1300, height: 1000 } });
  const p = await ctx.newPage();
  await p.goto(UI + '/user', { waitUntil: 'networkidle' });
  const erg = [];
  erg.push(await handlung(p, 'U0_nutzer_waehlen', async () => {
    await p.locator('li,div').filter({ hasText: /^admin/ }).getByRole('button', { name: 'Wählen' }).first().click()
      .catch(async () => { await p.getByRole('button', { name: 'Wählen' }).first().click(); });
  }));
  erg.push(await handlung(p, 'U0b_chat_seite', async () => { await p.getByRole('link', { name: 'Chat', exact: true }).first().click(); }));
  const karte = () => p.locator('text=Fall 06').filter({ hasNotText: 'Avatar' }).first().locator('xpath=ancestor::*[.//button[normalize-space()="Öffnen"]][1]');
  if ((await karte().getByRole('button', { name: 'Öffnen' }).count()) > 0) {
    if (opt('--storage-out')) await ctx.storageState({ path: opt('--storage-out') });
    erg.push(await handlung(p, 'U2_chat_reset', async () => { await karte().getByRole('button', { name: 'Chat-Reset' }).click(); }));
    erg.push(await handlung(p, 'U1_oeffnen', async () => { await karte().getByRole('button', { name: 'Öffnen' }).click(); }));
  } else {
    for (const n of ['U2_chat_reset', 'U1_oeffnen']) erg.push({ handlung: n, nicht_bedienbar: 'Session-Liste nicht geladen (keine Karte "Fall 06")' });
  }
  if (variante === 'ok') {
    // U4: ein Nutzer ohne Session (Einrichtung ueber die vorhandene API), dann Auswahl und Chat in der UI
    const r = await p.request.post(UI + '/api/users', { headers: { 'X-Matrix-Actor': 'leer06', 'Content-Type': 'application/json' },
                                                        data: { id: 'leer06', name: 'Leer 06' } });
    const anlage = r.status();
    // frischer Kontext ohne gespeicherten Nutzer: die Seite zeigt das Nutzerverzeichnis (admin sieht nur sich selbst)
    const ctx4 = await b.newContext({ viewport: { width: 1300, height: 1000 } });
    const p4 = await ctx4.newPage();
    await p4.goto(UI + '/user', { waitUntil: 'networkidle' });
    erg.push(await handlung(p4, 'U4_nutzer_ohne_session', async () => {
      await p4.locator('xpath=//*[normalize-space()="Leer 06"]/ancestor::*[.//button[normalize-space()="Wählen"]][1]')
        .getByRole('button', { name: 'Wählen' }).first().click();
      await p4.waitForTimeout(1500);
      await p4.getByRole('link', { name: 'Chat', exact: true }).first().click();
    }));
    erg[erg.length - 1].anlage_status = anlage;
    await ctx4.close();
  } else if (opt('--storage-in')) {
    // U3: Neuladen mit gespeichertem Nutzer "admin" waehrend des Ausfalls
    const ctx2 = await b.newContext({ viewport: { width: 1300, height: 1000 }, storageState: opt('--storage-in') });
    const p2 = await ctx2.newPage();
    erg.push(await handlung(p2, 'U3_neuladen_gespeicherter_nutzer', async () => {
      await p2.goto(UI + '/chat', { waitUntil: 'networkidle' }); await p2.waitForTimeout(3000);
    }));
    await ctx2.close();
  }
  fs.writeFileSync(out, JSON.stringify({ variante, code_erwartet: CODE, handlungen: erg }, null, 2));
  for (const e of erg) console.log(variante, e.handlung, e.nicht_bedienbar ? ('NICHT BEDIENBAR: ' + e.nicht_bedienbar) :
    JSON.stringify({ api: e.api.map(a => `${a.status} ${a.method} ${a.url} ${a.code || ''}`), ladefehler: e.sessions_ladefehler,
                     mit_code: e.ladefehler_mit_code, keine_session: e.keine_session_sichtbar, laedt: e.laedt_sichtbar,
                     karte: e.fall06_karte_sichtbar }).slice(0, 600));
  await b.close();
})();
