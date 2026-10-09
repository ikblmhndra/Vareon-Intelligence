import type { components } from "@/lib/api/schema";

export type CveFreshness = components["schemas"]["CveFreshness"];
export type CveCheckSource = components["schemas"]["CveCheckSource"];

/** Status run yang berarti sumber BENAR-BENAR dicek; sama dengan `SUCCESS_STATUSES` di
 * `apps/api/.../services/cve_check.py`. Selain ini (fetch_error, rate_limited, ...) = gagal. */
const CHECKED_STATUSES = new Set(["ok", "empty", "partial"]);

export function isFailedStatus(status: string | null): boolean {
  return status !== null && !CHECKED_STATUSES.has(status);
}

/** "12m ago" / "in 12m"; `nowMs` bisa disuntik buat test. */
export function relativeTime(iso: string, nowMs: number = Date.now()): string {
  const diffS = Math.round((Date.parse(iso) - nowMs) / 1000);
  const future = diffS > 0;
  const s = Math.abs(diffS);
  if (s < 60) return future ? "in <1m" : "just now";
  const min = Math.floor(s / 60);
  let span: string;
  if (min < 60) span = `${min}m`;
  else if (min < 48 * 60) span = `${Math.floor(min / 60)}h ${min % 60}m`;
  else span = `${Math.floor(min / 60 / 24)}d`;
  return future ? `in ${span}` : `${span} ago`;
}

const WIB = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Jakarta",
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** Hari kalender WIB, sama dengan dashboard CVE dan export Excel. */
export function formatWib(iso: string): string {
  return `${WIB.format(new Date(iso))} WIB`;
}

/** Slot cek otomatis terdekat dari sumber yang aktif; `null` kalau semuanya mati. */
export function nextAutoCheck(data: CveFreshness): string | null {
  const upcoming = data.sources.flatMap((s) => (s.enabled && s.next_check_at ? [s.next_check_at] : []));
  return upcoming.length ? upcoming.reduce((a, b) => (Date.parse(a) <= Date.parse(b) ? a : b)) : null;
}
