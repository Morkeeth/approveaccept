// Record the core flow: agents send purchases over MCP while the owner's inbox is open.
// Usage: AA_BASE=http://127.0.0.1:PORT AA_OWNER_TOKEN=... node record-inbox.cjs OUTDIR
// The Face ID step itself needs a phone; this recording stops at the approval link.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs'), path = require('path'), cp = require('child_process');
const out = process.argv[2], base = process.env.AA_BASE, token = process.env.AA_OWNER_TOKEN;
if (!out || !base || !token) { console.error('usage: AA_BASE=... AA_OWNER_TOKEN=... node record-inbox.cjs OUTDIR'); process.exit(2); }
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, recordVideo: { dir: out, size: { width: 390, height: 844 } } });
  const page = await ctx.newPage();
  const log = { base, started: new Date().toISOString(), steps: [], errors: [] };
  page.on('pageerror', e => log.errors.push(String(e)));
  const shot = async n => { await page.screenshot({ path: path.join(out, n + '.png') }); log.steps.push(n); };
  const pause = ms => page.waitForTimeout(ms);
  await page.goto(base + '/inbox');
  await page.fill('#key', token); await page.click('#gate button');
  await page.waitForSelector('#app:not([hidden])'); await pause(1200); await shot('01-empty-inbox');
  // The agents act now, over MCP, each with its own key.
  const driver = cp.spawnSync('python3', ['-B', path.join(__dirname, 'connect', 'demo_agents.py')],
    { env: { ...process.env, AA_URL: base, APPROVEACCEPT_OWNER_TOKEN: token }, encoding: 'utf8', timeout: 240000 });
  log.driver = driver.stdout.trim().split('\n'); if (driver.status !== 0) log.errors.push(driver.stderr.slice(-400));
  await page.waitForSelector('[data-approve]', { timeout: 15000 }); await pause(1500); await shot('02-waiting-grouped-by-agent');
  await page.evaluate(() => document.querySelector('#paid').scrollIntoView({ behavior: 'smooth', block: 'center' })); await pause(1600); await shot('03-paid-history');
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' })); await pause(900);
  await page.click('[data-approve]'); await page.waitForSelector('.req .out a'); await pause(1500); await shot('04-face-id-link');
  log.approval_link_shown = await page.$eval('.req .out a', a => a.textContent);
  await page.click('#t-agents'); await pause(1600); await shot('05-agents-limits');
  await page.click('#t-fun'); await pause(1400); await shot('06-surprise-me-tab');
  await page.click('#t-req'); await pause(800);
  await ctx.close(); await browser.close();
  const vid = fs.readdirSync(out).find(f => f.endsWith('.webm'));
  if (vid) fs.renameSync(path.join(out, vid), path.join(out, 'inbox.webm'));
  fs.writeFileSync(path.join(out, 'inbox.json'), JSON.stringify(log, null, 2));
  console.log(log.driver.join('\n')); console.log('errors', log.errors.length, log.errors);
})().catch(e => { console.error(e); process.exit(1); });
