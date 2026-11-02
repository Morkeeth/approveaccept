// Test for check-stamps.cjs: a planted stamp must fail both layers, the real page must pass.
// Run: node design/test-check-stamps.cjs
const { spawnSync } = require('child_process'), fs = require('fs'), os = require('os'), path = require('path');
const real = path.join(__dirname, 'index.html'), dir = fs.mkdtempSync(path.join(os.tmpdir(), 'stamp-'));
const run = (...a) => spawnSync(process.execPath, [path.join(__dirname, 'check-stamps.cjs'), ...a], { encoding: 'utf8' });
const designUrl = process.env.AA_DESIGN_URL || 'http://127.0.0.1:8754';
const planted = path.join(dir, 'planted.html');
fs.writeFileSync(planted, fs.readFileSync(real, 'utf8').replace('</main>', '<span class=stamp>Refused</span><p>Approved stamp</p></main>'));
const cases = [
  ['planted, static', run(planted, ''), 1],
  ['planted, rendered', run(planted, 'file://' + planted), 1],
  ['real page, static and rendered', run(real, designUrl), 0],
];
let bad = 0;
for (const [name, r, want] of cases) { const ok = r.status === want; bad += !ok;
  console.log(`${ok ? 'ok  ' : 'BAD '} ${name}: exit ${r.status}, want ${want}\n     ${r.stdout.trim().split('\n').join('\n     ')}`); }
fs.rmSync(dir, { recursive: true, force: true });
process.exit(bad ? 1 : 0);
