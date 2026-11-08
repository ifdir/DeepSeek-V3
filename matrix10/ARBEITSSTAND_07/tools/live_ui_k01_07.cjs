// Stand 07 / K-01: echte gebaute UI (START.py, frontend_dist) im Chromium - Bedienung wie ein Nutzer.
// Aufruf: node live_ui_k01_07.cjs <phase 1|2> <ausgabe.json> <screenshot-praefix> [--storage-in f] [--storage-out f]
// Phase 1: Nutzer "admin" waehlen, Konfiguration -> Provider "Nur lokale Synapse", Chat "Fall 06" oeffnen,
//          als Bedienperson senden, dann "Figuren jetzt weiterreden lassen".
// Phase 2 (nach Neustart des Servers): mit gespeichertem Nutzer Chat neu laden, Verlauf sichtbar?, erneut senden.
// Gemessen: jede /api/-Antwort (Status, Code), die Bodies von prepare/formulate/commit, sichtbarer Text, localStorage.
const { chromium } = require('playwright');
const fs = require('fs');
const args = process.argv.slice(2);
const [phase, out, shot] = args;
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : null; };
const UI = 'http://127.0.0.1:8180';

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1300, height: 1100 }, ...(opt('--storage-in') ? { storageState: opt('--storage-in') } : {}) });
  const p = await ctx.newPage();
  const api = [];
  const bodies = { prepare: [], formulate: [], commit: [], mcc: [] };
  p.on('response', async (r) => {
    const u = r.url();
    if (!u.includes('/api/') || u.includes('/api/health') || u.includes('/api/live-log')) return;
    let txt = ''; try { txt = await r.text(); } catch (e) {}
    let j = null; try { j = JSON.parse(txt); } catch (e) {}
    const path = u.replace(UI, '');
    api.push({ status: r.status(), method: r.request().method(), url: path.slice(0, 80), code: j && (j.code || j.error) || null });
    let req = null; try { req = JSON.parse(r.request().postData() || 'null'); } catch (e) {}
    if (path.startsWith('/api/kernel/prepare')) bodies.prepare.push({ status: r.status(), req, res: j });
    if (path.startsWith('/api/llm/formulate')) bodies.formulate.push({ status: r.status(), req, res: j });
    if (path.startsWith('/api/kernel/commit')) bodies.commit.push({ status: r.status(), req, res: j && { ok: j.ok, code: j.code, message: j.message } });
    if (path.startsWith('/api/mcc')) bodies.mcc.push({ status: r.status(), text: txt });
  });
  const ergebnis = { phase, schritte: [] };
  const schritt = async (name, fn, warte = 2500) => {
    let fehler = null;
    try { await fn(); } catch (e) { fehler = String(e).slice(0, 300); }
    await p.waitForTimeout(warte);
    await p.screenshot({ path: `${shot}_${name}.png`, fullPage: false });
    const alerts = await p.$$eval('[role=alert]', els => els.map(e => e.innerText.replace(/\s+/g, ' ').trim()).filter(Boolean));
    ergebnis.schritte.push({ name, fehler, alerts });
  };
  const sende = async (text) => {
    const box = p.getByPlaceholder('Sag etwas in der Szene…');
    await box.fill(text);
    await p.getByRole('button', { name: 'Senden', exact: true }).click();
    await p.waitForResponse((r) => r.url().includes('/api/kernel/commit'), { timeout: 60000 });
  };
  if (phase === '1') {
    await p.goto(UI + '/user', { waitUntil: 'networkidle' });
    await schritt('P1_nutzer', async () => {
      await p.locator('li,div').filter({ hasText: /^admin/ }).getByRole('button', { name: 'Wählen' }).first().click()
        .catch(async () => { await p.getByRole('button', { name: 'Wählen' }).first().click(); });
    });
    await schritt('P1_config_synapse', async () => {
      await p.goto(UI + '/config', { waitUntil: 'networkidle' });
      const sel = p.locator('label:has-text("Provider") select, select:has(option[value="synapse"])').first();
      await sel.selectOption('synapse');
      await p.waitForResponse((r) => r.url().includes('/api/config') && r.request().method() !== 'GET', { timeout: 15000 }).catch(() => {});
    });
    await schritt('P1_chat_oeffnen', async () => {
      await p.getByRole('link', { name: 'Chat', exact: true }).first().click();
      await p.waitForTimeout(1500);
      const karte = p.locator('text=Fall 06').filter({ hasNotText: 'Avatar' }).first().locator('xpath=ancestor::*[.//button[normalize-space()="Öffnen"]][1]');
      await karte.getByRole('button', { name: 'Öffnen' }).click();
      await p.waitForTimeout(2000);
      const spr = p.locator('[data-v92="spreche-als"]');
      if (await spr.count()) await spr.selectOption('operator').catch(() => {});
    });
    await schritt('P1_senden', async () => { await sende('Johann, wie geht es dir heute?'); }, 3500);
    await schritt('P1_weiterreden', async () => {
      await p.getByRole('button', { name: /Figuren jetzt weiterreden lassen/ }).click();
      await p.waitForResponse((r) => r.url().includes('/api/kernel/commit'), { timeout: 60000 });
    }, 4000);
    if (opt('--storage-out')) await ctx.storageState({ path: opt('--storage-out') });
  } else {
    await schritt('P2_neuladen_chat', async () => {
      await p.goto(UI + '/chat/ses_v92', { waitUntil: 'networkidle' });
    }, 3500);
    ergebnis.sichtbar_nach_neustart = (await p.innerText('body')).replace(/\s+/g, ' ');
    await schritt('P2_senden', async () => {
      const spr = p.locator('[data-v92="spreche-als"]');
      if (await spr.count()) await spr.selectOption('operator').catch(() => {});
      await sende('Mara, hast du gehört, was Johann gesagt hat?');
    }, 3500);
  }
  ergebnis.sichtbar = (await p.innerText('body')).replace(/\s+/g, ' ');
  ergebnis.localStorage = await p.evaluate(() => JSON.stringify(Object.assign({}, window.localStorage)));
  ergebnis.api = api;
  ergebnis.bodies = bodies;
  fs.writeFileSync(out, JSON.stringify(ergebnis, null, 2));
  console.log(phase, ergebnis.schritte.map(s => `${s.name}:${s.fehler ? 'FEHLER ' + s.fehler.slice(0, 120) : 'ok'}${s.alerts.length ? ' ALERT ' + s.alerts.join(' | ').slice(0, 160) : ''}`).join('\n'));
  console.log('api', api.filter(a => /prepare|formulate|commit|config/.test(a.url)).map(a => `${a.status} ${a.method} ${a.url} ${a.code || ''}`).join(' ; '));
  await b.close();
})();
