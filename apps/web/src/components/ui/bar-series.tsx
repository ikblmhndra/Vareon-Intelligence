"use client";

import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
  type ChartData,
} from "chart.js";
import { Chart } from "react-chartjs-2";

import { useChartTheme, withAlpha } from "@/lib/chart-theme";

// Registrasi sama dengan `components/dashboard/charts.tsx`; Line+Point untuk garis acuan.
ChartJS.register(CategoryScale, LinearScale, BarElement, LineElement, PointElement, Tooltip);

interface BarSeriesProps {
  labels: string[];
  values: number[];
  /** Batang yang disorot (warna `highlightTone`); gabungan dengan `highlightLast`. */
  highlight?: (index: number) => boolean;
  /** Sorot n batang terakhir. */
  highlightLast?: number;
  /** Garis horizontal acuan pada nilai ini (dataset garis, tanpa plugin). */
  referenceLine?: number;
  height?: number;
  "aria-label": string;
  /** Format nilai di tooltip dan tabel tersembunyi (mis. `${v} stories`); default angka apa adanya. */
  formatValue?: (v: number) => string;
  /** Warna batang yang tidak disorot. */
  tone?: "neutral" | "primary";
  highlightTone?: "primary" | "destructive";
}

/** Batang kecil Chart.js: warna dari variabel CSS (tema terang/gelap), tabel tersembunyi berisi data yang sama
 * untuk pembaca layar (kanvas tidak terbaca mereka). Dipakai kartu Overview entitas dan view Intelligence. */
export function BarSeries({
  labels,
  values,
  highlight,
  highlightLast,
  referenceLine,
  height = 180,
  "aria-label": ariaLabel,
  formatValue = String,
  tone = "primary",
  highlightTone = "primary",
}: BarSeriesProps) {
  const t = useChartTheme();
  const base = tone === "primary" ? t.primary : t.textDim;
  const hi = highlightTone === "destructive" ? t.critical : t.primary;
  const isHi = (i: number) =>
    (highlight?.(i) ?? false) || (highlightLast !== undefined && i >= values.length - highlightLast);
  const colors = values.map((_, i) => (isHi(i) ? hi : base));

  const data: ChartData<"bar" | "line", number[], string> = {
    labels,
    datasets: [
      {
        type: "bar",
        data: values,
        backgroundColor: colors,
        hoverBackgroundColor: colors.map((c) => withAlpha(c, 0.8)),
        borderWidth: 0,
        borderRadius: 4,
        borderSkipped: false,
        maxBarThickness: 28,
      },
      ...(referenceLine !== undefined
        ? [
            {
              type: "line" as const,
              data: values.map(() => referenceLine),
              borderColor: t.textBright,
              borderWidth: 1,
              borderDash: [4, 4],
              pointRadius: 0,
              pointHoverRadius: 0,
              fill: false,
            },
          ]
        : []),
    ],
  };

  return (
    <div role="group" aria-label={ariaLabel}>
      <div style={{ height }} aria-hidden="true">
        <Chart
          type="bar"
          data={data}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              tooltip: {
                filter: (c) => c.datasetIndex === 0,
                backgroundColor: t.surface,
                titleColor: t.textBright,
                bodyColor: t.textDim,
                borderColor: t.border,
                borderWidth: 1,
                padding: 10,
                cornerRadius: 12,
                callbacks: { label: (c) => formatValue(c.parsed.y ?? 0) },
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
      <table className="sr-only">
        <caption>{ariaLabel}</caption>
        <tbody>
          {labels.map((l, i) => (
            <tr key={`${l}-${i}`}>
              <th scope="row">{l}</th>
              <td>{formatValue(values[i])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
