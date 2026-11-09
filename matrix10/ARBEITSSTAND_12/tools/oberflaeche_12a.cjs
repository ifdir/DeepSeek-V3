// Stand 12A (Kettenkarte, Kettenvertrag §6.3 "Oberflaeche bis Oberflaeche"): die gebaute UI (START.py, frontend_dist) im Chromium.
// neu    : Nutzer admin waehlen, Chat-Seite, Welt waehlen, kein Avatar, anwesend = die genannten Figuren-IDs, "Neue Session"
//          -> gibt die neue Sitzungs-ID aus (die Sitzung entsteht auf dem Weg der Oberflaeche, nicht per Hand).
// lesen  : Nutzer admin waehlen, /chat/<sid> oeffnen, sichtbaren Text und Bildschirmfoto sichern (Anzeige = Beleg).
// Aufruf : node oberflaeche_12a.cjs neu <weltId> <id1,id2> <ausgabe.json>
//          node oberflaeche_12a.cjs lesen <sid> <ausgabe.json> <bild.png>
const { chromium } = require('playwright');
const fs = require('fs');
const UI = 'http://127.0.0.1:8180';
const [modus, a1, a2, a3, a4] = process.argv.slice(2);

async function nutzer(p) {
  await p.goto(UI + '/user', { waitUntil: 'networkidle' });
  await p.locator('li,div').filter({ hasText: /^admin/ }).getByRole('button', { name: 'Wählen' }).first().click()
    .catch(async () => { await p.getByRole('button', { name: 'Wählen' }).first().click(); });
  await p.waitForTimeout(800);
}

(async () => {
  const b = await chromium.launch();
  const p = await (await b.newContext({ viewport: { width: 1300, height: 1400 } })).newPage();
  const out = { modus, fehler: null };
  try {
    await nutzer(p);
    if (modus === 'neu') {
      const [welt, ids, aus] = [a1, a2.split(','), a3];
      await p.goto(UI + '/chat', { waitUntil: 'networkidle' });
      await p.locator('select[name=world]').selectOption(welt);
      await p.waitForTimeout(800);
      await p.locator('select[name=avatar]').selectOption('');
      for (const cb of await p.locator('input[name=present]').all()) {
        const v = await cb.getAttribute('value');
        if (ids.includes(v)) await cb.check(); else await cb.uncheck();
      }
      const antwort = p.waitForResponse((r) => r.url().includes('/api/sessions') && r.request().method() === 'POST', { timeout: 30000 });
      await p.getByRole('button', { name: 'Neue Session' }).click();
      const r = await antwort;
      const j = await r.json().catch(() => ({}));
      out.status = r.status();
      out.sessionId = (j.session && j.session.id) || j.id || null;
      fs.writeFileSync(aus, JSON.stringify(out, null, 1));
    } else {
      const [sid, aus, bild] = [a1, a2, a3];
      await p.goto(UI + '/chat/' + sid, { waitUntil: 'networkidle' });
      await p.waitForTimeout(2500);
      out.sichtbar = (await p.innerText('body')).replace(/[ \t]+/g, ' ');
      await p.screenshot({ path: bild, fullPage: true });
      fs.writeFileSync(aus, JSON.stringify(out, null, 1));
    }
  } catch (e) {
    out.fehler = String(e).slice(0, 400);
    fs.writeFileSync(modus === 'neu' ? a3 : a2, JSON.stringify(out, null, 1));
  }
  await b.close();
})();
