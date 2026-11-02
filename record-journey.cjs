// Drive the one-screen journey and record it. Usage: AA_BASE=http://127.0.0.1:PORT AA_OWNER_TOKEN=... node record-journey.cjs OUTDIR
// Leg A: Surprise me -> swipe -> yes on an idea inside the limit -> receipt.
// Leg B: same flow, yes on an idea over the limit -> held for Face ID. A headless browser
// cannot perform Face ID, so leg B stops at the held state and says so in journey.json.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs'), path = require('path');
const out = process.argv[2], base = process.env.AA_BASE, token = process.env.AA_OWNER_TOKEN;
if (!out || !base || !token) { console.error('usage: AA_BASE=... AA_OWNER_TOKEN=... node record-journey.cjs OUTDIR'); process.exit(2); }
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, recordVideo: { dir: out, size: { width: 390, height: 844 } } });
  const page = await ctx.newPage();
  const log = { base, started: new Date().toISOString(), legs: [], errors: [] };
  page.on('pageerror', e => log.errors.push(String(e)));
  const shot = n => page.screenshot({ path: path.join(out, n + '.png') });
  // Owner sign-in happens before the clock: it is the owner's own device.
  await page.goto(base + '/journey');
  await page.fill('#key', token); await page.click('#gate button');
  await page.waitForSelector('#app:not([hidden])'); await page.waitForTimeout(800); await shot('01-start');

  async function leg(name, pick) {
    const t0 = Date.now();
    await page.click('[data-mode=surprise]');
    await page.waitForSelector('.slide'); await page.waitForTimeout(900); await shot(name + '-02-reel');
    const ideas = await page.$$eval('.slide', s => s.map(x => ({ title: x.querySelector('h2').textContent, over: !!x.querySelector('.badge.fid') })));
    const n = ideas.findIndex(pick);
    if (n < 0) throw Error(name + ': no matching idea in ' + JSON.stringify(ideas));
    for (let k = 1; k <= Math.max(n, 2); k++) { await page.click(`[data-go="${k}"]`); await page.waitForTimeout(900); }
    await page.click(`[data-go="${n}"]`); await page.waitForTimeout(900); await shot(name + '-03-chosen');
    await page.click(`[data-yes="${n}"]`);
    await page.waitForSelector('#receipt, #fid', { timeout: 30000 }); await page.waitForTimeout(1500);
    await shot(name + '-04-result');
    const text = await page.$eval('#stage', e => e.innerText);
    log.legs.push({ name, ideas, chosen: n, seconds: (Date.now() - t0) / 1000, result: text });
    await page.evaluate(() => scrollTo(0, 0)); await page.waitForTimeout(600);
  }
  await leg('A-inside', i => !i.over);
  await leg('B-over', i => i.over);
  log.legs[1].note = 'Held for Face ID. Headless browser cannot perform Face ID; nothing captured.';
  await ctx.close(); await browser.close();
  const vid = fs.readdirSync(out).find(f => f.endsWith('.webm'));
  if (vid) fs.renameSync(path.join(out, vid), path.join(out, 'journey.webm'));
  fs.writeFileSync(path.join(out, 'journey.json'), JSON.stringify(log, null, 2));
  console.log(JSON.stringify(log.legs.map(l => ({ name: l.name, seconds: l.seconds, chosen: l.ideas[l.chosen] })), null, 1), 'errors', log.errors.length);
})().catch(e => { console.error(e); process.exit(1); });
