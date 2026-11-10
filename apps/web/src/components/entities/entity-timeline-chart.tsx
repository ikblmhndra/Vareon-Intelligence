"use client";

import { BarSeries } from "@/components/ui/bar-series";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** `2026-03` -> `Mar 2026`. */
function monthLabel(m: string): string {
  const [y, mo] = m.split("-");
  return `${MONTHS[Number(mo) - 1] ?? mo} ${y}`;
}

/** Batang artikel per bulan; dipakai kartu Overview (12 bulan) dan tab Timeline (24 bulan). Internalnya
 * `BarSeries` (Task 13); ekspor dan props tetap supaya pemanggil tidak berubah. */
export function EntityTimelineChart({
  months,
  height = 180,
  highlightLast,
}: {
  months: { month: string; articles: number }[];
  height?: number;
  /** Sorot n bulan terakhir (kartu Overview: dua batang terakhir primer, sisanya netral). */
  highlightLast?: number;
}) {
  const total = months.reduce((s, m) => s + m.articles, 0);
  return (
    <BarSeries
      labels={months.map((m) => monthLabel(m.month))}
      values={months.map((m) => m.articles)}
      height={height}
      {...(highlightLast ? { highlightLast, tone: "neutral" as const } : {})}
      formatValue={(v) => `${v} stories`}
      aria-label={`Mentions per month, ${total} stories over ${months.length} months`}
    />
  );
}
