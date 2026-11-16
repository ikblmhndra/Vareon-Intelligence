// Cek palet warna di globals.css (terang + gelap) tanpa dependensi:
// - ΔE2000 antar --chart-* >= 20 (kategori harus bisa dibedakan),
// - kontras --chart-* >= 3:1 terhadap --background & --surface (WCAG 1.4.11),
// - --intel-text >= 4.5:1 (teks), --intel beda >= 15 ΔE dari info/success/destructive.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const css = readFileSync(
  fileURLToPath(new URL("../src/app/globals.css", import.meta.url)),
  "utf8",
);

/** Ambil isi blok `selector { ... }` pertama yang selektornya persis cocok. */
function block(selector) {
  const re = new RegExp(`(^|\\n)${selector.replace(".", "\\.")}\\s*\\{`);
  const m = re.exec(css);
  if (!m) throw new Error(`blok ${selector} tidak ditemukan`);
  let i = m.index + m[0].length;
  const start = i;
  for (let depth = 1; depth > 0; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}") depth--;
  }
  return css.slice(start, i - 1);
}

function vars(body) {
  const out = {};
  for (const m of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}

const root = vars(block(":root"));
const dark = vars(block(".dark"));

function resolve(theme, name, seen = new Set()) {
  const own = theme === "dark" ? dark : root;
  let val = own[name] ?? (theme === "dark" ? root[name] : undefined);
  if (val === undefined) return undefined;
  const alias = /^var\((--[\w-]+)\)$/.exec(val);
  if (alias) {
    if (seen.has(name)) throw new Error(`alias melingkar: ${name}`);
    seen.add(name);
    return resolve(theme, alias[1], seen);
  }
  return /^#[0-9a-f]{6}$/i.test(val) ? val.toLowerCase() : undefined;
}

const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);

function luminance(hex) {
  const [r, g, b] = rgb(hex).map(lin);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function lab(hex) {
  const [r, g, b] = rgb(hex).map(lin);
  const x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047;
  const y = 0.2126729 * r + 0.7151522 * g + 0.072175 * b;
  const z = (0.0193339 * r + 0.119192 * g + 0.9503041 * b) / 1.08883;
  const f = (t) => (t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116);
  const [fx, fy, fz] = [f(x), f(y), f(z)];
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

/** CIEDE2000 (Sharma et al. 2005). */
function deltaE(h1, h2) {
  const [L1, a1, b1] = lab(h1);
  const [L2, a2, b2] = lab(h2);
  const rad = Math.PI / 180;
  const C1 = Math.hypot(a1, b1);
  const C2 = Math.hypot(a2, b2);
  const Cb = (C1 + C2) / 2;
  const G = 0.5 * (1 - Math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)));
  const ap1 = (1 + G) * a1;
  const ap2 = (1 + G) * a2;
  const Cp1 = Math.hypot(ap1, b1);
  const Cp2 = Math.hypot(ap2, b2);
  const hp = (b, a) => (b === 0 && a === 0 ? 0 : ((Math.atan2(b, a) / rad) + 360) % 360);
  const hp1 = hp(b1, ap1);
  const hp2 = hp(b2, ap2);
  const dLp = L2 - L1;
  const dCp = Cp2 - Cp1;
  let dhp = 0;
  if (Cp1 * Cp2 !== 0) {
    dhp = hp2 - hp1;
    if (dhp > 180) dhp -= 360;
    else if (dhp < -180) dhp += 360;
  }
  const dHp = 2 * Math.sqrt(Cp1 * Cp2) * Math.sin((dhp * rad) / 2);
  const Lbp = (L1 + L2) / 2;
  const Cbp = (Cp1 + Cp2) / 2;
  let hbp = hp1 + hp2;
  if (Cp1 * Cp2 !== 0) {
    if (Math.abs(hp1 - hp2) > 180) hbp += hp1 + hp2 < 360 ? 360 : -360;
    hbp /= 2;
  }
  const T =
    1 -
    0.17 * Math.cos((hbp - 30) * rad) +
    0.24 * Math.cos(2 * hbp * rad) +
    0.32 * Math.cos((3 * hbp + 6) * rad) -
    0.2 * Math.cos((4 * hbp - 63) * rad);
  const dTheta = 30 * Math.exp(-(((hbp - 275) / 25) ** 2));
  const Rc = 2 * Math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7));
  const Sl = 1 + (0.015 * (Lbp - 50) ** 2) / Math.sqrt(20 + (Lbp - 50) ** 2);
  const Sc = 1 + 0.045 * Cbp;
  const Sh = 1 + 0.015 * Cbp * T;
  const Rt = -Math.sin(2 * dTheta * rad) * Rc;
  return Math.sqrt(
    (dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh),
  );
}

const MIN_DE = 20;
const MIN_DE_INTEL = 15;
let failures = 0;

for (const theme of ["light", "dark"]) {
  const get = (n) => resolve(theme, n);
  const fail = (msg) => {
    failures++;
    console.log(`  GAGAL [${theme}] ${msg}`);
  };
  const before = failures;
  const need = (n) => {
    const v = get(n);
    if (!v) fail(`${n} tidak ada / bukan hex`);
    return v;
  };

  const bg = need("--background");
  const surfaces = [bg, need("--surface")].filter(Boolean);
  const card = get("--card");
  if (card) surfaces.push(card);

  const charts = [];
  for (let i = 1; i <= 10; i++) charts.push([`--chart-${i}`, need(`--chart-${i}`)]);

  for (let i = 0; i < charts.length; i++) {
    const [n, h] = charts[i];
    if (!h) continue;
    for (const s of surfaces) {
      const c = contrast(h, s);
      if (c < 3) fail(`${n} ${h} vs ${s}: kontras ${c.toFixed(2)} < 3`);
    }
    for (let j = i + 1; j < charts.length; j++) {
      const [n2, h2] = charts[j];
      if (!h2) continue;
      const de = deltaE(h, h2);
      if (de < MIN_DE) fail(`${n} ${h} vs ${n2} ${h2}: ΔE ${de.toFixed(1)} < ${MIN_DE}`);
    }
  }

  const intelText = need("--intel-text");
  if (intelText) {
    for (const s of surfaces) {
      const c = contrast(intelText, s);
      if (c < 4.5) fail(`--intel-text ${intelText} vs ${s}: kontras ${c.toFixed(2)} < 4.5`);
    }
  }
  const intel = need("--intel");
  if (intel) {
    for (const o of ["--info", "--success", "--destructive"]) {
      const h = get(o);
      if (!h) continue;
      const de = deltaE(intel, h);
      if (de < MIN_DE_INTEL)
        fail(`--intel ${intel} vs ${o} ${h}: ΔE ${de.toFixed(1)} < ${MIN_DE_INTEL}`);
    }
  }

  if (failures === before) console.log(`  OK [${theme}] palet lolos semua cek`);
}

if (failures) {
  console.log(`\n${failures} cek gagal`);
  process.exit(1);
}
console.log("\ncheck:palette lolos");
