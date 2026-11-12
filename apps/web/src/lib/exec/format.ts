import { csvCell } from "@/lib/csv";

/** Selisih KPI vs periode sebelumnya (D14): `percent` untuk jumlah artikel, `absolute` untuk sektor dan aktor.
 * Naik = lebih banyak berita/aktor = BURUK (merah), turun = baik (hijau). Teks tanpa kata "vs prev": pemanggil
 * menambahkannya (Briefing ringkas, Analyst board lengkap dengan jumlah hari, C13). `percent` dengan pembanding
 * 0 mengembalikan null (persen dari nol tak bermakna); `absolute` tetap bermakna. */
export function execDelta(
  current: number,
  prev: number,
  mode: "percent" | "absolute",
): { text: string; colorClass: string } | null {
  if (mode === "percent" && !prev) return null;
  const delta = current - prev;
  const colorClass =
    delta > 0 ? "text-destructive-text" : delta < 0 ? "text-success-text" : "text-muted-foreground";
  const sign = delta > 0 ? "+" : delta < 0 ? "-" : "";
  const amount = mode === "percent" ? `${Math.abs(Math.round((delta / prev) * 100))}%` : String(Math.abs(delta));
  return { text: `${sign}${amount}`, colorClass };
}

/** Batas tier risiko (satu skala: LOW <40, MED 40-69, HIGH >=70), dipakai juga
 * oleh `risk-matrix-view.tsx`. */
export const RISK_MED_MIN = 40;
export const RISK_HIGH_MIN = 70;

export function riskTier(score: number): { label: string; colorClass: string } {
  if (score >= RISK_HIGH_MIN) return { label: "HIGH", colorClass: "text-destructive" };
  if (score >= RISK_MED_MIN) return { label: "MED", colorClass: "text-warning" };
  return { label: "LOW", colorClass: "text-success" };
}

/** Port peer benchmark (`exec.js:138-154`) -- share sektor ini dari total
 * insiden semua sektor (dari `sector_trend`) vs rata-rata share per
 * sektor, murni dihitung client-side (gak dibalikin API). */
export function sectorPeerBenchmark(
  sectorTrend: { sector: string; data: number[] }[],
  sector: string,
): { text: string; colorClass: string } {
  const totals = sectorTrend.map((s) => ({ sector: s.sector, total: s.data.reduce((a, b) => a + b, 0) }));
  const grandTotal = totals.reduce((a, b) => a + b.total, 0) || 1;
  const avgPct = totals.length > 0 ? 100 / totals.length : 0;
  const thisTotal = totals.find((t) => t.sector === sector)?.total ?? 0;
  const pct = (thisTotal / grandTotal) * 100;
  const diff = pct - avgPct;
  const colorClass = diff > 5 ? "text-destructive" : diff > 0 ? "text-primary" : "text-muted-foreground";
  return { text: `${diff >= 0 ? "+" : ""}${diff.toFixed(1)}% vs avg`, colorClass };
}

/** Kelas teks untuk di atas tint `bg-X/15` yang diturunkan dari kelas warna dinamis. Pemetaan LITERAL
 * (bukan string-concat `${c}-text`) supaya Tailwind menemukan dan meng-generate kelas `-text`-nya. */
const ON_TINT: Record<string, string> = {
  "text-destructive": "text-destructive-text",
  "text-warning": "text-warning-text",
  "text-success": "text-success-text",
  "text-primary": "text-primary-text",
};
export const onTint = (colorClass: string): string => ON_TINT[colorClass] ?? colorClass;

export function taConfidenceColor(conf: number | null): string {
  if (conf === null) return "text-muted-foreground";
  if (conf >= 80) return "text-success";
  if (conf >= 50) return "text-primary";
  return "text-destructive";
}

export function cvssColorClass(score: number | null | undefined): string {
  const v = score ?? 0;
  if (v >= 9) return "text-destructive";
  if (v >= 7) return "text-warning";
  if (v >= 4) return "text-primary";
  return "text-muted-foreground";
}

const csvRow = (cells: unknown[]): string => cells.map(csvCell).join(",");

/** Port `exportExecCsv()` (`exec.js:687-728`). Sel lewat `csvCell` (guard formula Excel + kutip). */
export function buildExecCsv(d: import("@/lib/api/loose-types").ExecDashboardV2, countLabel: string): string {
  const prevSet = new Set(d.prev_ta_names.map((n) => n.toLowerCase()));
  const rows: string[] = [
    csvRow(["=== SECTOR RISK MATRIX ==="]),
    csvRow(["Sector", "Risk Score", "Top Actor"]),
    ...d.sector_risk_scores.map((r) => csvRow([r.sector, r.risk_score, r.top_actor])),
    "",
    csvRow(["=== TOP THREAT ACTORS ==="]),
    csvRow(["Threat Actor", "Incident Count", "Status", "Velocity %", "Top Sectors"]),
    ...d.ta_leaderboard.map((ta) =>
      csvRow([
        ta.name,
        ta.count,
        !d.prev_period_reliable ? "n/a" : prevSet.has(ta.name.toLowerCase()) ? "RECURRING" : "NEW",
        ta.velocity_pct,
        ta.top_sectors,
      ]),
    ),
    "",
    csvRow(["=== MONTHLY TOTALS ==="]),
    csvRow(["Month", "Incidents"]),
    ...d.months.map((m, i) => csvRow([m, d.monthly_totals[i] ?? 0])),
    "",
    csvRow(["=== SECTOR TREND ==="]),
    csvRow(["Name", ...d.months]),
    ...d.sector_trend.map((s) => csvRow([s.sector, ...s.data])),
    "",
    csvRow(["=== VICTIM COUNTRY TREND ==="]),
    csvRow(["Name", ...d.months]),
    ...d.victim_country_trend.map((s) => csvRow([s.country, ...s.data])),
    "",
    csvRow(["=== CVE EXPOSURE ==="]),
    csvRow(["Technology", "Total", "Critical", "High", "Medium", "Max CVSS", "PoC Count"]),
    ...d.cve_exposure_v2.map((r) => csvRow([r.tech, r.total, r.critical, r.high, r.medium, r.max_cvss, r.poc_count])),
    "",
    csvRow(["=== SPIKE ALERTS ==="]),
    csvRow(["Sector/Industry", "Date", "Count", "Z-Score", "Severity"]),
    ...d.industry_spikes.map((sp) => csvRow([sp.entity, sp.date, sp.count, sp.z_score, sp.severity])),
    "",
    csvRow(["=== KPI SUMMARY ==="]),
    csvRow(["Metric", "Value"]),
    csvRow([countLabel, d.total_incidents]),
    csvRow(["Active Sectors", d.active_sectors ?? d.top_sectors.length]),
    csvRow(["Unique Threat Actors", d.unique_ta_count ?? d.ta_leaderboard.length]),
    csvRow(["Critical CVEs", d.cve_kpis.critical]),
    csvRow(["KEV CVEs", d.cve_kpis.kev]),
    csvRow(["Highest Risk Sector", d.sector_risk_scores[0]?.sector ?? ""]),
    csvRow(["Highest Risk Score", d.sector_risk_scores[0]?.risk_score ?? 0]),
    csvRow(["Active Spikes", d.industry_spikes.length]),
  ];
  return rows.join("\n");
}

export function downloadExecCsv(d: import("@/lib/api/loose-types").ExecDashboardV2, countLabel: string): void {
  const csv = buildExecCsv(d, countLabel);
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `cti-exec-dashboard-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/** Nama sektor dari API huruf kecil ("financial services"); tampil sebagai judul kata. */
export function toTitleCase(s: string): string {
  return s.replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
}

/** Rumus skor risiko sektor, ditampilkan di tooltip "How is risk scored?" (kartu Sector risk). */
export const RISK_FORMULA_TITLE =
  "Risk Score = Volume(0-50) + Trend(0-20) + Spike(0-30)\n• Volume: (last_month / max_sector) × 50\n• Trend: increase first→second half, max 20\n• Spike: z-score × 10, capped at 30";

/** Awal jendela dashboard sebagai "YYYY-MM-DD" lokal (hari ini − `days`), sama dengan awal rentang di header
 * halaman. Tautan hitungan ke Newsroom membawanya sebagai `from` supaya jumlah artikel di sheet sama dengan
 * angka di kartu. */
export function execWindowFrom(days: number, today: Date): string {
  const s = new Date(today.getFullYear(), today.getMonth(), today.getDate() - days);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${s.getFullYear()}-${p(s.getMonth() + 1)}-${p(s.getDate())}`;
}

/** Velocity aktor: merah hanya di atas +20% (C15); `null` (riwayat belum cukup) tampil "—". */
export function velocityDisplay(pct: number | null): { text: string; colorClass: string } {
  if (pct === null) return { text: "—", colorClass: "text-muted-foreground" };
  return {
    text: `${pct > 0 ? "+" : ""}${pct}%`,
    colorClass: pct > 20 ? "text-destructive-text" : "text-muted-foreground",
  };
}

/** Singkatan header kolom matriks aktor × sektor (6.2). Kunci = nama sektor dari API (huruf kecil); sektor yang
 * belum terdaftar jatuh ke 7 huruf pertama kapital, nama lengkap selalu ada di `<abbr title>`. */
// Kunci = nama tampilan di packages/cti-core/src/cti_core/entity/sectors.py (huruf kecil); varian ber-kurung
// harus berbeda supaya header kolom tak bentrok.
export const SECTOR_ABBR: Record<string, string> = {
  aerospace: "AERO",
  agriculture: "AGRI",
  automotive: "AUTO",
  chemical: "CHEM",
  commercial: "COMM.",
  communications: "COMMS",
  construction: "CONSTR",
  defense: "DEFENSE",
  education: "EDU",
  "emergency services": "EMERG.",
  energy: "ENERGY",
  entertainment: "ENTERT.",
  "financial services": "FINANCE",
  government: "GOV",
  "government (local)": "GOV-LOC",
  "government (national)": "GOV-NAT",
  "government (public services)": "GOV-PUB",
  "government (regional)": "GOV-REG",
  healthcare: "HEALTH",
  "hospitality & leisure": "HOSP.",
  infrastructure: "INFRA",
  "infrastructure (dams)": "INF-DAM",
  "infrastructure (nuclear)": "INF-NUC",
  "infrastructure (water)": "INF-WAT",
  insurance: "INSUR.",
  manufacturing: "MANUF.",
  mining: "MINING",
  "non-profit": "NONPROF",
  pharmaceuticals: "PHARMA",
  retail: "RETAIL",
  technology: "TECH",
  telecommunications: "TELECOM",
  transportation: "TRANSP.",
  utilities: "UTIL.",
};

export const sectorAbbr = (sector: string): string =>
  SECTOR_ABBR[sector.toLowerCase()] ?? sector.slice(0, 7).toUpperCase();
