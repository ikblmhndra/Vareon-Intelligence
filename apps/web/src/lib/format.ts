// Formatter tanggal/waktu zona browser (spec 2a, D2): semua tampilan memakai zona waktu browser lewat
// `Intl`, bukan UTC. Nilai tanggal-saja ("YYYY-MM-DD": published, detected_on, remediation_date_plan)
// TIDAK BOLEH bergeser sehari di zona barat UTC, jadi di-parse sebagai tanggal kalender LOKAL.

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;
const MS_DAY = 86_400_000;

/** "YYYY-MM-DD" -> Date pada tengah malam LOKAL. `new Date("2026-11-02")` itu UTC tengah malam, yang di
 * Los Angeles jatuh ke 1 Nov 16:00; fungsi ini menghindarinya.
 * Contoh: parseLocalDate("2026-11-02").getDate() === 2 di zona mana pun. */
export function parseLocalDate(isoDate: string): Date {
  const m = DATE_ONLY.exec(isoDate);
  if (!m) return new Date(isoDate);
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

const DASH = "—";

/** Date valid, atau null untuk input kosong/tak valid (Intl melempar RangeError pada Date tak valid). */
function toDate(value: string | Date | null | undefined): Date | null {
  if (value == null || value === "") return null;
  const d = value instanceof Date ? value : parseLocalDate(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "2 Nov"; "12 Nov 2026" bila tahunnya beda dengan tahun sekarang (atau `withYear`, dipakai `DateField`
 * yang butuh tahun selalu tampil). Tanggal-saja tidak bergeser.
 * Contoh: fmtShortDate("2026-11-02") === "2 Nov" (tahun berjalan 2026), di zona UTC-8 juga. */
export function fmtShortDate(
  value: string | Date | null | undefined,
  opts?: { withYear?: boolean },
): string {
  const d = toDate(value);
  if (!d) return DASH;
  const sameYear = !opts?.withYear && d.getFullYear() === new Date().getFullYear();
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
  }).format(d);
}

/** "Mar 2021" (bulan + tahun, zona browser); dipakai tile "First seen" di pratinjau entity. */
export function fmtMonthYear(value: string | Date | null | undefined): string {
  const d = toDate(value);
  if (!d) return DASH;
  return new Intl.DateTimeFormat("en-GB", { month: "short", year: "numeric" }).format(d);
}

function part(parts: Intl.DateTimeFormatPart[], type: Intl.DateTimeFormatPartTypes): string {
  return parts.find((p) => p.type === type)?.value ?? "";
}

/** "2 Nov 14:20 GMT+7" (zona browser, offset pendek). */
export function fmtDateTime(value: string | Date | null | undefined): string {
  const d = toDate(value);
  if (!d) return DASH;
  const p = new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZoneName: "shortOffset",
  }).formatToParts(d);
  return `${part(p, "day")} ${part(p, "month")} ${part(p, "hour")}:${part(p, "minute")} ${part(p, "timeZoneName")}`;
}

/** "14:20" (24 jam, zona browser). */
export function fmtTime(value: string | Date | null | undefined): string {
  const d = toDate(value);
  if (!d) return DASH;
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(d);
}

/** Umur ringkas tanpa "ago": "now", "5 m", "2 h", "1 d", "2 w", "3 mo", "1 y". */
export function fmtCompactAge(
  value: string | Date | null | undefined,
  nowMs: number = Date.now(),
): string {
  const date = toDate(value);
  if (!date) return DASH;
  const sec = Math.max(0, Math.floor((nowMs - date.getTime()) / 1000));
  const min = Math.floor(sec / 60);
  if (min < 1) return "now";
  if (min < 60) return `${min} m`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} h`;
  const d = Math.floor(h / 24);
  if (d < 14) return `${d} d`;
  if (d < 60) return `${Math.floor(d / 7)} w`;
  if (d < 365) return `${Math.floor(d / 30)} mo`;
  return `${Math.floor(d / 365)} y`;
}

/** Umur relatif untuk kalimat: "just now" (bukan "now ago"), "5 m ago", "2 d ago"; nilai kosong = "—". */
export function fmtAgo(value: string | Date | null | undefined, nowMs: number = Date.now()): string {
  const age = fmtCompactAge(value, nowMs);
  if (age === DASH) return age;
  return age === "now" ? "just now" : `${age} ago`;
}

/** Sisa hari kedaluwarsa: "today", "in 1 day", "in 5 days" (nilai negatif dianggap hari ini). */
export function fmtDaysLeft(days: number): string {
  const n = Math.max(Math.round(days), 0);
  return n === 0 ? "today" : `in ${n} ${n === 1 ? "day" : "days"}`;
}

/** ISO dengan offset untuk tengah malam lokal, mis. "2026-11-08T00:00:00+07:00" (batas "hari ini" ke API). */
export function fmtLocalDayStart(now: Date = new Date()): string {
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const pad = (n: number) => String(Math.trunc(Math.abs(n))).padStart(2, "0");
  const off = -start.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  return (
    `${start.getFullYear()}-${pad(start.getMonth() + 1)}-${pad(start.getDate())}T00:00:00` +
    `${sign}${pad(off / 60)}:${pad(off % 60)}`
  );
}

/** Nama zona browser, mis. "Asia/Jakarta" (fallback "UTC"). */
export function browserZoneName(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

/** Selisih hari kalender (zona browser) dari hari ini ke `isoDate`; negatif = sudah lewat.
 * `null` untuk input kosong/tak valid: pemanggil harus menanganinya. */
export function daysUntil(isoDate: string | null | undefined, now: Date = new Date()): number | null {
  const target = toDate(isoDate);
  if (!target) return null;
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((target.getTime() - today.getTime()) / MS_DAY);
}
