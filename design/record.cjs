// Three screen recordings of the 8754 design variant. Nothing here calls 8752 or PayPal.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs'), out = process.argv[2];
// Stamp gate: no recording while "stamp" is in a class name or visible text.
const gate = require('child_process').spawnSync('node', [__dirname + '/check-stamps.cjs'], { encoding: 'utf8' });
console.log(gate.stdout.trim()); if (gate.status !== 0) process.exit(1);
// Token gate: no recording while the brown and shiny tokens have drifted (design/tokens.json).
const tok = require('child_process').spawnSync('node', [__dirname + '/check-tokens.cjs'], { encoding: 'utf8' });
console.log(tok.stdout.trim()); if (tok.status !== 0) process.exit(1);
const HD = { width: 1920, height: 1080 };
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined });
  const clip = async (name, size, fn) => {
    // CDP screencast frames, encoded later by the system ffmpeg (Playwright's own ffmpeg is not installed).
    const ctx = await browser.newContext({ viewport: size, colorScheme: 'dark' });
    const page = await ctx.newPage(); const errs = []; page.on('pageerror', e => errs.push(String(e)));
    const dir = `${out}/frames-${name}`; fs.rmSync(dir, { recursive: true, force: true }); fs.mkdirSync(dir, { recursive: true });
    await page.goto('http://127.0.0.1:8754');
    const cdp = await ctx.newCDPSession(page); const frames = [];
    cdp.on('Page.screencastFrame', async f => { const n = frames.length; fs.writeFileSync(`${dir}/${String(n).padStart(5, '0')}.jpg`, Buffer.from(f.data, 'base64'));
      frames.push(f.metadata.timestamp); try { await cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }) } catch (e) {} });
    await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 90, maxWidth: size.width, maxHeight: size.height, everyNthFrame: 1 });
    await fn(page); const tEnd = Date.now() / 1000; await cdp.send('Page.stopScreencast');
    const ov = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    await ctx.close();
    const lines = frames.map((t, i) => `file '${String(i).padStart(5, '0')}.jpg'\nduration ${((frames[i + 1] ?? tEnd) - t).toFixed(3)}`);
    fs.writeFileSync(`${dir}/list.txt`, lines.join('\n') + `\nfile '${String(frames.length - 1).padStart(5, '0')}.jpg'\n`);
    console.log(name, 'frames', frames.length, 'span', (frames.at(-1) - frames[0]).toFixed(1) + 's', 'errors', errs.length, 'overflow', ov);
  };
  const slide = async (page, from, to, ms) => { const steps = Math.abs(to - from); for (let i = 0; i <= steps; i++) {
    const v = from + Math.sign(to - from) * i; await page.evaluate(v => { const r = document.querySelector('#energy'); r.value = v; r.dispatchEvent(new Event('input')) }, v); await page.waitForTimeout(ms / steps) } };
  await clip('accept', HD, async page => {
    await page.evaluate(() => document.querySelector('#zone-pend').scrollIntoView({ block: 'start' })); await page.waitForTimeout(5200);
    await page.locator('.accept').first().click(); await page.waitForTimeout(1800);
    await page.locator('.wcard').first().click(); await page.waitForTimeout(2200);
    await page.locator('.wcard').first().click(); await page.waitForTimeout(1200);
    await page.locator('.refuse').first().click(); await page.waitForTimeout(2600);
  });
  await clip('persona', HD, async page => {
    await page.waitForTimeout(1500); await slide(page, 22, 85, 3000); await page.waitForTimeout(2200);
    await slide(page, 85, 20, 3000); await page.waitForTimeout(2200);
    await page.evaluate(() => { const r = document.querySelector('#food'); r.value = 90; r.dispatchEvent(new Event('input')) }); await page.evaluate(() => { const r = document.querySelector('#energy'); r.value = 50; r.dispatchEvent(new Event('input')) });
    await page.waitForTimeout(2400);
  });
  await clip('incident', HD, async page => {
    // Plain list: scroll to it and hold. Nothing animates.
    await page.evaluate(() => document.querySelector('#zone-inc').scrollIntoView({ block: 'start' })); await page.waitForTimeout(4500);
    await page.mouse.wheel(0, 500); await page.waitForTimeout(5000);
  });
  await browser.close();
})();
