import type { components } from "@/lib/api/schema";

export type CveDashboardData = components["schemas"]["CveDashboard"];
export type MetricStat = components["schemas"]["MetricStat"];
export type StatusKey = keyof components["schemas"]["StatusBreakdown"];

export const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Urutan siklus hidup CVE di dashboard (dari belum disentuh sampai selesai). */
export const STATUS_ORDER: { key: StatusKey; label: string; hint: string }[] = [
  { key: "unacknowledged", label: "Unacknowledged", hint: "Belum di-acknowledge dan belum punya ticket" },
  { key: "awaiting_status", label: "Awaiting status", hint: "Sudah di-acknowledge / punya ticket, status remediation masih kosong" },
  { key: "open", label: "Open", hint: "Remediation belum dimulai" },
  { key: "in_progress", label: "In Progress", hint: "Remediation sedang berjalan" },
  { key: "risk_accepted", label: "Risk Accepted", hint: "Risiko diterima" },
  { key: "completed", label: "Completed", hint: "Resolved atau Closed" },
  { key: "not_affected", label: "Not Affected", hint: "Risk acceptance = No Risk (Not Affected)" },
];

export const STATUS_LABEL: Record<string, string> = Object.fromEntries(STATUS_ORDER.map((s) => [s.key, s.label]));

/** `null` = tidak ada data; angka bulat tanpa desimal, selain itu 1 desimal. */
export function fmtDays(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export function fmtPercent(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "—";
  return `${Math.round(rate * 100)}%`;
}

export type Rating = { label: string; dotClass: string };

/** Di bawah porsi ini (CVE yang sudah di-acknowledge / semua CVE di baris) rata-rata MTTA tidak
 * mewakili baris: MTTA "3 hari" dari 4 dari 32 CVE critical bukan kinerja "Good" (audit UI U19). */
export const MIN_ACK_SHARE_FOR_RATING = 0.5;

/**
 * Rating dari rata-rata MTTA (hari) -- ambang sama dengan sheet Excel lama
 * (<=1 Excellent, <=7 Good, <=14 Fair, selebihnya Needs Improvement).
 * BUKAN SLA per severity: belum ada target SLA yang ditetapkan, jadi CRITICAL
 * dan LOW dinilai dengan penggaris yang sama. `acknowledged`/`total` opsional: bila kurang dari
 * `MIN_ACK_SHARE_FOR_RATING` yang sudah di-acknowledge, baris dinilai dari backlog-nya, bukan
 * dari segelintir CVE yang cepat ditangani.
 */
export function ratingForMtta(
  meanDays: number | null | undefined,
  acknowledged?: number,
  total?: number,
): Rating | null {
  if (total && acknowledged !== undefined && acknowledged / total < MIN_ACK_SHARE_FOR_RATING) {
    return { label: "Backlog", dotClass: "bg-destructive" };
  }
  if (meanDays === null || meanDays === undefined) return null;
  if (meanDays <= 1) return { label: "Excellent", dotClass: "bg-success" };
  if (meanDays <= 7) return { label: "Good", dotClass: "bg-info" };
  if (meanDays <= 14) return { label: "Fair", dotClass: "bg-warning" };
  return { label: "Needs improvement", dotClass: "bg-destructive" };
}

export const SEVERITY_DOT_CLASS: Record<string, string> = {
  CRITICAL: "bg-severity-critical",
  HIGH: "bg-severity-high",
  MEDIUM: "bg-severity-medium",
  LOW: "bg-severity-low",
};
