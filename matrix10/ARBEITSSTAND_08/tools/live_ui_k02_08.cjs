// Stand 08 / K-02: echte gebaute UI (START.py, frontend_dist) im Chromium.
// Aufruf: node live_ui_k02_08.cjs <phase 1|2> <ausgabe.json> <screenshot-praefix> [--storage-in f] [--storage-out f]
// Phase 1: Nutzer "admin", Konfiguration "Nur lokale Synapse", Chat "Fall 06", als Bedienperson das Ereignis senden.
// Phase 2 (nach Neustart): Gedaechtnisseite -> Session "Fall 06", Figur Mara -> "Recall" (Stichwort), dann Figur Robert.
const { chromium } = require('playwright');
const fs = require('fs');
const args = process.argv.slice(2);
const [phase, out, shot] = args;
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : null; };
const UI = 'http://127.0.0.1:8180';
const EREIGNIS = 'Johann, die Kasse im Keller ist leer.';

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1300, height: 1100 }, ...(opt('--storage-in') ? { storageState: opt('--storage-in') } : {}) });
  const p = await ctx.newPage();
  const api = [];
  const recalls = [];
  p.on('response', async (r) => {
    const u = r.url();
    if (!u.includes('/api/') || u.includes('/api/health') || u.includes('/api/live-log')) return;
    let j = null; try { j = await r.json(); } catch (e) {}
    const path = u.replace(UI, '');
    api.push({ status: r.status(), method: r.request().method(), url: path.slice(0, 80), code: j && (j.code || j.error) || null });
    if (path.includes('/recall')) { let req = null; try { req = JSON.parse(r.request().postData() || 'null'); } catch (e) {} recalls.push({ status: r.status(), req, res: j }); }
  });
  const E = { phase, schritte: [] };
  const schritt = async (name, fn, warte = 2500) => {
    let fehler = null;
    try { await fn(); } catch (e) { fehler = String(e).slice(0, 300); }
    await p.waitForTimeout(warte);
    await p.screenshot({ path: `${shot}_${name}.png`, fullPage: false });
    E.schritte.push({ name, fehler });
  };
  if (phase === '1') {
    await p.goto(UI + '/user', { waitUntil: 'networkidle' });
    await schritt('P1_nutzer', async () => {
      await p.locator('li,div').filter({ hasText: /^admin/ }).getByRole('button', { name: 'Wählen' }).first().click()
        .catch(async () => { await p.getByRole('button', { name: 'Wählen' }).first().click(); });
    });
    await schritt('P1_config_synapse', async () => {
      await p.goto(UI + '/config', { waitUntil: 'networkidle' });
      await p.locator('select:has(option[value="synapse"])').first().selectOption('synapse');
      await p.waitForResponse((r) => r.url().includes('/api/config') && r.request().method() !== 'GET', { timeout: 15000 }).catch(() => {});
    });
    await schritt('P1_senden', async () => {
      await p.goto(UI + '/chat/ses_v92', { waitUntil: 'networkidle' });
      const spr = p.locator('[data-v92="spreche-als"]');
      if (await spr.count()) await spr.selectOption('operator').catch(() => {});
      await p.getByPlaceholder('Sag etwas in der Szene…').fill(EREIGNIS);
      await p.getByRole('button', { name: 'Senden', exact: true }).click();
      await p.waitForResponse((r) => r.url().includes('/api/kernel/commit'), { timeout: 60000 });
    }, 3500);
    if (opt('--storage-out')) await ctx.storageState({ path: opt('--storage-out') });
  } else {
    const abruf = async (figur) => {
      const sels = p.locator('main select, select');
      await sels.nth(0).selectOption('ses_v92');
      await sels.nth(1).selectOption(figur);
      await p.getByPlaceholder('Recall-Stichwort').fill('Kasse Keller');
      await p.locator('[data-k02="figur-recall"]').click();
      await p.waitForResponse((r) => r.url().includes('/recall'), { timeout: 15000 });
      await p.waitForTimeout(800);
      return (await p.innerText('body')).replace(/\s+/g, ' ');
    };
    await p.goto(UI + '/memory', { waitUntil: 'networkidle' });
    await p.waitForTimeout(1500);
    let tm = '', tr = '';
    await schritt('P2_recall_mara', async () => { tm = await abruf('char_g7_mara'); });
    await schritt('P2_recall_robert', async () => { tr = await abruf('char_g7_robert'); });
    const zeile = (t, name) => { const i = t.indexOf(`Abruf von ${name}`); return i >= 0 ? t.slice(i, i + 400) : ''; };
    E.mara_zeile = zeile(tm, 'Mara');
    E.robert_zeile = zeile(tr, 'Robert');
  }
  E.api = api;
  E.recalls = recalls;
  fs.writeFileSync(out, JSON.stringify(E, null, 2));
  console.log(phase, E.schritte.map(s => `${s.name}:${s.fehler ? 'FEHLER ' + s.fehler.slice(0, 140) : 'ok'}`).join('\n'));
  if (phase === '2') console.log('MARA:', E.mara_zeile.slice(0, 200), '\nROBERT:', E.robert_zeile.slice(0, 200));
  await b.close();
})();
