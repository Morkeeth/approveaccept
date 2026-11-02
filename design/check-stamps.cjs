// Fails (exit 1) if "stamp" appears in a CSS class name or in visible text. The owner ruled stamps out.
// Usage: node design/check-stamps.cjs [file.html] [url]   defaults: design/index.html and http://127.0.0.1:8754
// Layer 1 reads the HTML source: class attributes, CSS selectors, classList calls, text between tags.
// Layer 2 renders the page and reads every element's class and document.body.innerText.
// JS identifiers such as "timestamp" in record.cjs are not class names or visible text, so they are not read.
const fs = require('fs'), path = require('path');
const file = process.argv[2] || path.join(__dirname, 'index.html');
const url = process.argv[3] ?? 'http://127.0.0.1:8754';
const RE = /stamp/i, hits = [];

function staticCheck(src) {
  const lines = src.split('\n');
  lines.forEach((ln, i) => {
    const at = `${path.basename(file)}:${i + 1}`;
    for (const m of ln.matchAll(/class(?:Name)?\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/g)) if (RE.test(m[1])) hits.push(`${at} class attribute ${m[1]}`);
    for (const m of ln.matchAll(/\.([A-Za-z_-][\w-]*)/g)) if (RE.test(m[1]) && !/\.(timestamp)\b/.test(m[0])) hits.push(`${at} selector or classList .${m[1]}`);
    for (const m of ln.matchAll(/classList\.\w+\(([^)]*)\)/g)) if (RE.test(m[1])) hits.push(`${at} classList ${m[1]}`);
  });
  const text = src.replace(/<style[\s\S]*?<\/style>/gi, '').replace(/<script[\s\S]*?<\/script>/gi, '').replace(/<[^>]+>/g, ' ');
  for (const m of text.matchAll(/[^\s]*stamp[^\s]*/gi)) hits.push(`${path.basename(file)} visible text "${m[0]}"`);
  // Template strings inside scripts render as text: read the text between tags inside them too.
  for (const m of src.matchAll(/>([^<>`$]*stamp[^<>`$]*)</gi)) hits.push(`${path.basename(file)} template text "${m[1].trim()}"`);
}

function playwrightAvailable() {
  // Playwright is an optional dev dependency. Without it, the source check still runs and the rendered layer says it was skipped.
  if (process.env.APPROVEACCEPT_FORCE_NO_PLAYWRIGHT === '1') return false;  // test seam
  try { require.resolve('playwright'); return true; } catch (_) {}
  const py = require('child_process').spawnSync('python3', ['-c', 'import playwright'], { encoding: 'utf8' });
  return py.status === 0;
}

async function renderedCheck() {
  if (!playwrightAvailable()) {
    console.log('SKIPPED rendered check: Playwright is an optional dev dependency (npm install playwright, or pip install playwright and then playwright install chromium). The source check still ran.');
    return false;
  }
  let r;
  try {
    const { chromium } = require('playwright');
    const launch = { headless: true };
    if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH) launch.executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
    const browser = await chromium.launch(launch), page = await browser.newPage();
    await page.goto(url); await page.waitForTimeout(2500);
    r = await page.evaluate(() => ({
      classes: [...document.querySelectorAll('*')].flatMap(e => [...e.classList]).filter(c => /stamp/i.test(c)),
      text: (document.body.innerText.match(/\S*stamp\S*/gi) || []),
    }));
    await browser.close();
  } catch (nodeError) {
    const run = require('child_process').spawnSync('python3', [path.join(__dirname, 'check-stamps-rendered.py'), url],
      { encoding: 'utf8', env: process.env });
    if (run.status !== 0) throw Error((run.stderr || run.stdout || nodeError.message).trim());
    r = JSON.parse(run.stdout);
  }
  r.classes.forEach(c => hits.push(`${url} rendered class .${c}`));
  r.text.forEach(t => hits.push(`${url} rendered text "${t}"`));
  return true;
}

(async () => {
  staticCheck(fs.readFileSync(file, 'utf8'));
  const rendered = url ? await renderedCheck() : false;
  if (hits.length) { console.log(`FAIL check-stamps: ${hits.length} hit(s)\n` + [...new Set(hits)].join('\n')); process.exit(1); }
  console.log(`PASS check-stamps: 0 hits in ${file}${rendered ? ' and rendered ' + url : ' (source only)'}`);
})().catch(e => { console.log('FAIL check-stamps: ' + e.message); process.exit(1); });
