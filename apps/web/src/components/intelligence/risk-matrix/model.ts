import { countryName } from "@/lib/countries";
import { RISK_HIGH_MIN, RISK_MED_MIN } from "@/lib/exec/format";
import type { RiskMatrixCell } from "@/lib/api/loose-types";

export type Trend = "rising" | "falling" | "stable";

/** Panah backend (↑ ↓ →) -> kata; dipakai `aria-label` dan ikon sel. */
export function trendOf(cell: RiskMatrixCell): Trend {
  return cell.trend === "↑" ? "rising" : cell.trend === "↓" ? "falling" : "stable";
}

/** Tier skor, satu skala dengan `Chip kind="risk"` (`RISK_MED_MIN` 40 / `RISK_HIGH_MIN` 70). */
export function tierOf(score: number): "low" | "med" | "high" {
  return score >= RISK_HIGH_MIN ? "high" : score >= RISK_MED_MIN ? "med" : "low";
}

export const cellKey = (c: Pick<RiskMatrixCell, "industry" | "country">) => `${c.industry}||${c.country}`;

/** "Finance × Indonesia": respons memakai kode ISO negara, tampilan memakai namanya. */
export const pairLabel = (c: Pick<RiskMatrixCell, "industry" | "country">) =>
  `${c.industry} × ${countryName(c.country)}`;

/** Perubahan jumlah artikel vs periode pembanding: "+56%", "-20%", "new" bila periode pembanding kosong. */
export function changeText(cell: RiskMatrixCell): string {
  if (cell.previous_count === 0) return "new";
  const pct = Math.round((cell.current_count / cell.previous_count - 1) * 100);
  return `${pct > 0 ? "+" : ""}${pct}%`;
}

/** Tanggal kalender "YYYY-MM-DD" dari `generated_at` (UTC) dikurangi `days`. Backend menghitung jendela
 * sebagai `posted_on >= date.today() - days` di zona proses server (UTC di compose) dan men-cache hasilnya
 * 15 menit; `generated_at` adalah saat hitung itu, jadi tanggal ini persis batas bawah yang dipakai
 * matriks (inklusif, sama dengan `posted_on_start` Newsroom), tidak bergantung zona browser. */
export function periodFrom(generatedAt: string, days: number): string {
  const d = new Date(generatedAt);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}
