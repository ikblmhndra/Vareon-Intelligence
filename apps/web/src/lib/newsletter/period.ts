const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Edisi newsletter = bulan kalender menurut zona laporan (WIB), bukan zona browser: peristiwa
// pukul 02:00 WIB tanggal 1 jatuh di bulan itu walau browser di UTC-8 masih melihat tanggal 31.
// Konstanta ini mencerminkan `WORKER__REPORT_UTC_OFFSET_HOURS` (default 7); klien tidak bisa
// membaca setelan server, jadi kalau offset itu diubah, ubah juga di sini (spec 4a, C16/9).
const REPORT_UTC_OFFSET_HOURS = 7;

export interface MonthOption {
  /** `YYYY-MM`. */
  value: string;
  /** Hari pertama dan terakhir bulan itu, `YYYY-MM-DD` (dikirim sebagai `period_start`/`period_end`). */
  start: string;
  end: string;
  /** Mis. "1 – 31 Oct 2026". */
  label: string;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** `value` (`YYYY-MM`) -> jendela bulan itu; null kalau bukan bulan yang valid. */
export function monthWindow(value: string): MonthOption | null {
  const m = /^(\d{4})-(\d{2})$/.exec(value);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  if (month < 1 || month > 12) return null;
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return {
    value,
    start: `${value}-01`,
    end: `${value}-${pad(last)}`,
    label: `1 – ${last} ${MONTHS[month - 1]} ${year}`,
  };
}

/** Enam bulan kalender SELESAI terakhir (WIB), terbaru dulu. Bulan berjalan tidak ditawarkan:
 * saran dibangun untuk bulan penuh (bulan sebelumnya adalah bawaan server). */
export function recentMonths(now: Date = new Date()): MonthOption[] {
  const wib = new Date(now.getTime() + REPORT_UTC_OFFSET_HOURS * 3_600_000);
  const out: MonthOption[] = [];
  for (let i = 1; i <= 6; i++) {
    // Date.UTC menormalkan bulan <= 0 ke Desember tahun sebelumnya.
    const d = new Date(Date.UTC(wib.getUTCFullYear(), wib.getUTCMonth() - i, 1));
    const w = monthWindow(`${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}`);
    if (w) out.push(w);
  }
  return out;
}

/** Jumlah hari inklusif antara dua tanggal `YYYY-MM-DD`. */
export function daysIn(start: string, end: string): number {
  const ms = (s: string) => Date.parse(`${s}T00:00:00Z`);
  return Math.round((ms(end) - ms(start)) / 86_400_000) + 1;
}
