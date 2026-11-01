"use client";

import { BarElement, CategoryScale, Chart as ChartJS, LinearScale, Tooltip } from "chart.js";
import { Bar } from "react-chartjs-2";

import { useChartTheme, withAlpha } from "@/lib/chart-theme";

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip);

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** `2026-03` -> `Mar 2026`. */
function monthLabel(m: string): string {
  const [y, mo] = m.split("-");
  return `${MONTHS[Number(mo) - 1] ?? mo} ${y}`;
}

/** Batang artikel per bulan; dipakai kartu Overview (12 bulan) dan tab Timeline (24 bulan). */
export function EntityTimelineChart({
  months,
  height = 180,
}: {
  months: { month: string; articles: number }[];
  height?: number;
}) {
  const t = useChartTheme();
  const labels = months.map((m) => monthLabel(m.month));
  const total = months.reduce((s, m) => s + m.articles, 0);
  return (
    <div
      style={{ height }}
      role="img"
      aria-label={`Mentions per month, ${total} stories over ${months.length} months`}
    >
      <Bar
        data={{
          labels,
          datasets: [
            {
              data: months.map((m) => m.articles),
              backgroundColor: t.primary,
              hoverBackgroundColor: withAlpha(t.primary, 0.8),
              borderWidth: 0,
              borderRadius: 4,
              borderSkipped: false,
              maxBarThickness: 28,
            },
          ],
        }}
        options={{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: t.surface,
              titleColor: t.textBright,
              bodyColor: t.textDim,
              borderColor: t.border,
              borderWidth: 1,
              padding: 10,
              cornerRadius: 12,
              callbacks: { label: (c) => `${c.parsed.y} stories` },
            },
          },
          scales: {
            x: {
              grid: { display: false },
              border: { display: false },
              ticks: { color: t.textDim, maxRotation: 0, autoSkip: true, maxTicksLimit: 6 },
            },
            y: {
              beginAtZero: true,
              border: { display: false },
              grid: { color: withAlpha(t.border, 0.6), drawTicks: false },
              ticks: { color: t.textDim, precision: 0 },
            },
          },
        }}
      />
    </div>
  );
}
