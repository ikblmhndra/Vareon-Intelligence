import type { ExecDashboardV2 } from "@/lib/api/loose-types";
import { toTitleCase } from "@/lib/exec/format";
import { parseLocalDate } from "@/lib/format";

/** Langkah warna heatmap sektor untuk sel tak kosong: 2..5. Langkah 1 (`bg-primary/10`) nyaris tak terlihat di atas
 * kartu mode gelap (hampir hitam), jadi sel terkecil mulai dari langkah 2 dan "kosong" digambar sebagai kotak
 * berbingkai (`HeatCell value={null}`), bukan langkah 0. */
export function heatStep(count: number, max: number): 0 | 2 | 3 | 4 | 5 {
  if (count <= 0 || max <= 0) return 0;
  return (Math.min(4, Math.max(1, Math.ceil((count / max) * 4))) + 1) as 2 | 3 | 4 | 5;
}

/** "Nov" untuk "2026-11" (zona browser; tanggal kalender lokal, tidak bergeser). */
export function monthShort(yyyymm: string): string {
  return new Intl.DateTimeFormat("en-GB", { month: "short" }).format(parseLocalDate(`${yyyymm}-01`));
}

/** "November 2026". */
export function monthLong(yyyymm: string): string {
  return new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" }).format(parseLocalDate(`${yyyymm}-01`));
}

/** Akhir bulan "YYYY-MM-DD" lewat aritmetika lokal. `toISOString()` menggeser sehari di zona timur UTC. */
export function monthEnd(yyyymm: string): string {
  const [y, m] = yyyymm.split("-").map(Number);
  const last = new Date(y, m, 0).getDate();
  return `${yyyymm}-${String(last).padStart(2, "0")}`;
}

/** "1 month" / "6 months": salinan mengikuti `months.length`, bukan teks tetap (C9). */
export function monthsCopy(n: number): string {
  return n === 1 ? "1 month" : `${n} months`;
}

/** Kalimat insight heatmap (D8), deterministik di klien. Kandidat: sektor dengan >= 3 bulan sebelumnya yang
 * berisi artikel dan bulan terakhirnya melampaui maksimum bulan-bulan sebelumnya itu; kenaikan terbesar menang.
 * Sektor yang baru muncul (riwayat < 3 bulan) tidak dihitung: "bulan tertinggi" dari satu-dua titik menyesatkan.
 * `null` = tidak ada yang memenuhi, kalimat disembunyikan. */
export function heatInsight(d: Pick<ExecDashboardV2, "sector_heatmap" | "months">): string | null {
  let best: { sector: string; month: string; count: number; gain: number } | null = null;
  for (const row of d.sector_heatmap) {
    if (row.months.length < 2) continue;
    const last = row.months[row.months.length - 1];
    const earlier = row.months.slice(0, -1);
    if (earlier.filter((m) => m.count > 0).length < 3) continue;
    const prevMax = Math.max(...earlier.map((m) => m.count));
    const gain = last.count - prevMax;
    if (gain > 0 && (best === null || gain > best.gain)) {
      best = { sector: row.sector, month: last.month, count: last.count, gain };
    }
  }
  if (!best) return null;
  const name = new Intl.DateTimeFormat("en-GB", { month: "long" }).format(parseLocalDate(`${best.month}-01`));
  return `${toTitleCase(best.sector)} reached its highest month in ${name} (${best.count} articles).`;
}
