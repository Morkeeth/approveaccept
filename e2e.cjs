// End to end click test. Usage: node e2e.cjs live|substitute OUTDIR
// Clicks every button in the one flow and screenshots each state. Dialog texts are recorded.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs'), path = require('path');
const mode = process.argv[2], out = process.argv[3];
const base = process.env.AA_BASE || (mode === 'live' ? 'http://127.0.0.1:8752' : 'http://127.0.0.1:8753');
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined });
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  const log = { mode, base, started: new Date().toISOString(), steps: [], dialogs: [], errors: [] };
  page.on('pageerror', e => log.errors.push(String(e)));
  page.on('dialog', async d => { log.dialogs.push(d.message()); await d.accept(); });
  const idle = () => page.waitForFunction(() => !document.querySelector('.busy'), null, { timeout: 240000 });
  const shot = async (name, full = true) => { await page.screenshot({ path: path.join(out, name + '.png'), fullPage: full }); log.steps.push(name); };
  const click = async (loc) => { await loc.click(); await page.waitForTimeout(300); await idle(); };
  const hold = (ev) => page.locator('#now .hold.wait', { hasText: ev }).first(); // waiting cards sit at the top

  await page.goto(base); await idle(); await shot('01-home');
  await page.setViewportSize({ width: 390, height: 860 }); await shot('01-home-390', false); await page.setViewportSize({ width: 1440, height: 1000 });

  await click(page.getByRole('button', { name: 'Book date night Saturday' }));
  await shot('02-date-night-proposed');

  if (mode === 'live') {
    await click(hold('Date night').getByRole('button', { name: 'I approved in PayPal, hold it' }));
    await shot('03-live-hold-without-buyer-approval');
  } else {
    await click(hold('Date night').getByRole('button', { name: 'I approved in PayPal, hold it' }));
    await shot('03-held-your-call');
    await click(hold('Date night').getByRole('button', { name: 'Accept' }));
    await shot('04-accepted-captured');
    await click(page.getByRole('button', { name: "Mum's birthday present" }));
    await click(hold("Headphones").getByRole('button', { name: 'I approved in PayPal, hold it' }));
    await shot('05-over-threshold-device-locked');
    await click(hold("Headphones").getByRole('button', { name: 'Sign on device' }));
    await shot('06-device-signed');
    await click(hold("Headphones").getByRole('button', { name: 'Accept' }));
  }
  await page.fill('#persona', 'Into films and quiet evenings. Hates loud bars. Vegetarian.');
  await click(page.getByRole('button', { name: 'Save persona' }));
  await click(page.getByRole('button', { name: 'Book date night Saturday' }));
  await shot('07-persona-edit-changed-proposal');
  if (mode !== 'live') {
    await click(hold('Date night').getByRole('button', { name: 'I approved in PayPal, hold it' }));
    await click(hold('Date night').getByRole('button', { name: 'Refuse' }));
    await shot('08-refused-voided');
  }
  await click(page.getByRole('button', { name: 'Errands, buy something' }));
  await shot('09-errands-refused');
  await click(page.getByRole('button', { name: 'What did agents spend on date nights?' }));
  await shot('10-query-answer');
  await click(page.getByRole('button', { name: 'Read back from PayPal' }));
  await shot('11-readback');
  await click(page.getByRole('button', { name: 'Run the attack set' }));
  await shot('12-attacks');
  log.finished = new Date().toISOString();
  fs.writeFileSync(path.join(out, 'e2e.json'), JSON.stringify(log, null, 1));
  console.log(JSON.stringify(log, null, 1));
  await browser.close();
})().catch(e => { console.error('E2E FAIL', e.message); process.exit(1); });
