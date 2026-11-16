const INT = /^\d+$/;
const STEP = /^\*\/\d+$/;

/**
 * Cron scraper jadi kata pendek untuk tabel. Hanya bentuk yang dipakai registry yang dikenali
 * (M, H, D bilangan tunggal); sisanya (daftar, rentang, bulan, enam field) dikembalikan apa adanya
 * supaya jadwal aneh tidak diterjemahkan salah.
 */
export function humanizeCron(expr: string): string {
  const f = expr.trim().split(/\s+/);
  if (f.length !== 5) return expr;
  const [m, h, dom, mon, dow] = f;
  if (dom !== "*" || mon !== "*") return expr;
  if (h === "*" && dow === "*") {
    if (STEP.test(m)) return `${m} min`;
    return INT.test(m) ? "hourly" : expr;
  }
  if (!INT.test(m)) return expr;
  if (STEP.test(h) && dow === "*") return `${h} h`;
  if (INT.test(h) && dow === "*") return "daily";
  if (INT.test(h) && INT.test(dow)) return "weekly";
  return expr;
}

/** False bila `humanizeCron` menyerah: pemanggil mencetak string mentah dalam `font-code`. */
export function isHumanized(expr: string): boolean {
  return humanizeCron(expr) !== expr;
}
