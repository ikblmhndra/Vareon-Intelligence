import type { RecapKind } from "@/lib/api/loose-types";

/**
 * Tanggal recap = tanggal KALENDER UTC, sama dengan backend (pekan Senin-Minggu menurut tanggal
 * UTC, `cti_api.services.recap.week_window`). Semua hitungan di sini lewat `Date.UTC`/`getUTC*`,
 * bukan zona waktu browser, supaya "Senin" tidak bergeser buat pengguna di zona lain.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY_MS = 86_400_000;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function parseIso(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function toIso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function dayMonth(iso: string): string {
  const d = parseIso(iso);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

/** `"2026-09-28", "2026-10-04"` -> `"28 Sep - 4 Oct"`; satu hari: `"28 Sep"`. */
export function formatRange(start: string, end: string): string {
  return start === end ? dayMonth(start) : `${dayMonth(start)} - ${dayMonth(end)}`;
}

/** Senin pekan yang memuat `iso` (`YYYY-MM-DD`); `""` kalau `iso` kosong/tidak valid (input date
 * yang dikosongkan), supaya pemanggil jatuh ke default server, bukan `RangeError`. */
export function mondayOf(iso: string): string {
  if (!ISO_DATE.test(iso)) return "";
  const d = parseIso(iso);
  const sinceMonday = (d.getUTCDay() + 6) % 7;
  return toIso(new Date(d.getTime() - sinceMonday * DAY_MS));
}

export function sundayOf(mondayIso: string): string {
  return toIso(new Date(parseIso(mondayIso).getTime() + 6 * DAY_MS));
}

/** Senin pekan terakhir yang SUDAH selesai di UTC: yang dibuat server kalau `week_start` kosong. */
export function lastFinishedWeekStart(todayIso: string = toIso(new Date())): string {
  return toIso(new Date(parseIso(mondayOf(todayIso)).getTime() - 7 * DAY_MS));
}

/** `Weekly Recap · 28 Sep - 4 Oct` atau `Daily Recap · 2026-10-06`. */
export function recapTitle(
  kind: RecapKind,
  date: string,
  periodStart?: string,
  periodEnd?: string,
): string {
  if (kind === "weekly") {
    return `Weekly Recap · ${formatRange(periodStart ?? date, periodEnd ?? sundayOf(date))}`;
  }
  return `Daily Recap · ${date}`;
}
