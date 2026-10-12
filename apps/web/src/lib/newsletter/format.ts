const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parts(iso: string): { day: number; month: string; year: number } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? { day: Number(m[3]), month: MONTHS[Number(m[2]) - 1], year: Number(m[1]) } : null;
}

/** `2026-10-01`, `2026-10-31` -> `1 - 31 Oct 2026`; lintas bulan `28 Sep - 4 Oct 2026`; lintas
 * tahun menyebut kedua tahun. Tanggal ISO dibaca sebagai teks (tanpa zona waktu browser). */
export function formatPeriodRange(start: string, end: string): string {
  const a = parts(start);
  const b = parts(end);
  if (!a || !b) return `${start} - ${end}`;
  if (a.year !== b.year) return `${a.day} ${a.month} ${a.year} - ${b.day} ${b.month} ${b.year}`;
  if (a.month !== b.month) return `${a.day} ${a.month} - ${b.day} ${b.month} ${b.year}`;
  if (a.day === b.day) return `${a.day} ${a.month} ${a.year}`;
  return `${a.day} - ${b.day} ${b.month} ${b.year}`;
}

/** Waktu saran dibangun, dalam WIB (zona kerja tim; server menyimpan UTC). */
export function formatBuiltAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Jakarta" })} WIB`;
}

/** Pesan galat dari objek `error` openapi-fetch (`{detail}` string atau daftar `{msg}` dari 422),
 * atau dari `Error` biasa. `String(e)` pada objek polos menghasilkan "[object Object]". */
export function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  if (e && typeof e === "object" && "detail" in e) {
    const detail = (e as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d))).join("; ");
    }
  }
  return "Unknown error";
}
