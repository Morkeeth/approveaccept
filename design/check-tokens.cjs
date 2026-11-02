// Fails (exit 1) if the main colour and type tokens drift from design/tokens.json (approved look, frozen 19 Oct).
// Usage: node design/check-tokens.cjs [file.html ...]   default: the files listed in tokens.json.
// Reads the first :root{...} block of each file (the dark default) and compares every frozen token exactly.
const fs = require('fs'), path = require('path');
const root = path.resolve(__dirname, '..');
const T = JSON.parse(fs.readFileSync(path.join(__dirname, 'tokens.json'), 'utf8'));
const files = process.argv.slice(2).length ? process.argv.slice(2) : T.files.map(f => path.join(root, f));
const norm = v => v.replace(/\s+/g, ' ').trim();
let bad = 0;
for (const f of files) {
  const src = fs.readFileSync(f, 'utf8');
  const m = src.match(/:root\s*\{([^}]*)\}/);
  if (!m) { console.log(`${f}: FAIL no :root block`); bad++; continue; }
  const got = {};
  for (const d of m[1].split(';')) { const i = d.indexOf(':'); if (i > 0) got[d.slice(0, i).trim()] = norm(d.slice(i + 1)); }
  const drift = Object.entries(T.dark).filter(([k, v]) => got[k] !== norm(v)).map(([k, v]) => `${k} is ${got[k] ?? 'missing'}, want ${v}`);
  console.log(`${path.relative(root, f)}: ${drift.length ? 'FAIL ' + drift.join('; ') : 'PASS ' + Object.keys(T.dark).length + ' tokens'}`);
  bad += drift.length ? 1 : 0;
}
process.exit(bad ? 1 : 0);
