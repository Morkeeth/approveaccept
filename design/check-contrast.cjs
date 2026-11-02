// Fails (exit 1) if a text colour on its ground is under WCAG AA (4.5:1) in either theme of index.html.
// Reads the dark :root block and the :root[data-theme=light] block, converts OKLCH to sRGB, compares pairs.
// Usage: node design/check-contrast.cjs [index.html]
const fs = require('fs'), path = require('path');
const file = process.argv[2] || path.resolve(__dirname, '..', 'index.html');
const src = fs.readFileSync(file, 'utf8');
const block = re => { const m = src.match(re); if (!m) throw new Error('block missing: ' + re); const o = {};
  for (const d of m[1].split(';')) { const i = d.indexOf(':'); if (i > 0) o[d.slice(0, i).trim()] = d.slice(i + 1).trim(); } return o; };
const dark = block(/:root\s*\{([^}]*)\}/), light = { ...dark, ...block(/:root\[data-theme=light\]\s*\{([^}]*)\}/) };
function rgb(v) {
  const m = /oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/.exec(v); if (!m) throw new Error('not oklch: ' + v);
  const [L, C, h] = [+m[1], +m[2], +m[3] * Math.PI / 180], a = C * Math.cos(h), b = C * Math.sin(h);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3, mm = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3, s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [4.0767416621 * l - 3.3077115913 * mm + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * mm - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * mm + 1.707614701 * s]
    .map(x => Math.min(1, Math.max(0, x)));
}
const lum = c => { const [r, g, b] = rgb(c); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const ratio = (x, y) => { const [a, b] = [lum(x), lum(y)].sort((p, q) => q - p); return (a + 0.05) / (b + 0.05); };
// Every text-on-ground pair the flow uses: body, muted lines, the Accept button, paid and refused words.
const PAIRS = [['--ink', '--ground'], ['--ink', '--panel'], ['--ink', '--raise'], ['--mute', '--ground'], ['--mute', '--panel'], ['--mute', '--raise'],
  ['--accink', '--acc'], ['--acc', '--panel'], ['--ok', '--panel'], ['--red', '--panel'], ['--red', '--ground']];
let bad = 0;
for (const [name, T] of [['dark', dark], ['light', light]]) {
  const rows = PAIRS.filter(([f, g]) => T[f] && T[g]).map(([f, g]) => { const r = ratio(T[f], T[g]); if (r < 4.5) bad++; return `${f} on ${g} ${r.toFixed(2)}${r < 4.5 ? ' FAIL' : ''}`; });
  console.log(`${name}: ${rows.join(' | ')}`);
}
console.log(bad ? `FAIL ${bad} pairs under 4.5:1` : 'PASS every pair at 4.5:1 or more');
process.exit(bad ? 1 : 0);
