// Screenshots for page 74. Before = 8752 home, loaded only, nothing clicked. After = 8754.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const out = process.argv[2];
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined });
  const errs = [];
  const shot = async (url, name, w, h, scheme, full) => {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: scheme });
    const page = await ctx.newPage(); page.on('pageerror', e => errs.push(name + ': ' + e));
    await page.goto(url); await page.waitForTimeout(4800);
    await page.screenshot({ path: `${out}/${name}.png`, fullPage: full }); await ctx.close();
  };
  await shot('http://127.0.0.1:8752', 'before-1440', 1440, 1000, 'dark', false);
  await shot('http://127.0.0.1:8754', 'after-1440-dark', 1440, 1000, 'dark', false);
  await shot('http://127.0.0.1:8754', 'after-1440-dark-full', 1440, 1000, 'dark', true);
  await shot('http://127.0.0.1:8754', 'after-1440-light-full', 1440, 1000, 'light', true);
  await shot('http://127.0.0.1:8754', 'after-390', 390, 860, 'dark', false);
  await shot('http://127.0.0.1:8754', 'after-390-full', 390, 860, 'dark', true);
  console.log('errors', JSON.stringify(errs)); await browser.close();
})();
