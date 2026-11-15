"use client";

import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
  type TooltipItem,
} from "chart.js";
import { Bar, Doughnut, Line } from "react-chartjs-2";

import { assignCategorySlots } from "@/lib/category-colors";
import { cssVar, useChartTheme, withAlpha, type ChartTheme } from "@/lib/chart-theme";
import { shortTickLabel } from "@/lib/chart-ticks";

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  ArcElement,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
);

/** Warna dibaca dari token tema via `useChartTheme` (Chart.js render ke
 * `<canvas>`, tidak bisa resolve `var(--x)`), jadi chart ikut light/dark.
 * Port dari `legacy/static/js/newsroom/dashboard.js`. */
if (typeof document !== "undefined") {
  const brand = cssVar("--font-google-sans-flex");
  ChartJS.defaults.font.family = brand ? `${brand}, system-ui, sans-serif` : "system-ui, sans-serif";
}
ChartJS.defaults.font.size = 12;

function tooltipBase(t: ChartTheme) {
  return {
    backgroundColor: t.surface,
    titleColor: t.textBright,
    bodyColor: t.textDim,
    borderColor: t.border,
    borderWidth: 1,
    padding: 10,
    cornerRadius: 12,
    boxPadding: 4,
    usePointStyle: true,
  };
}

const gridLine = (t: ChartTheme) => ({ color: withAlpha(t.border, 0.6), drawTicks: false });

/** Legenda satu gaya: titik/garis kecil (bukan kotak), teks redup. */
const legendBase = (t: ChartTheme, pointStyle: "line" | "circle") => ({
  position: "bottom" as const,
  labels: { color: t.textDim, usePointStyle: true, pointStyle, boxWidth: 8, font: { size: 12 } },
});

/** Tick sumbu x tanggal: label diringkas (`8 Nov`), tidak diputar, dilewati bila padat. */
const dateTicks = (t: ChartTheme, labels: string[]) => ({
  color: t.textDim,
  maxRotation: 0,
  autoSkip: true,
  maxTicksLimit: 8,
  callback: (_v: string | number, i: number) => shortTickLabel(labels[i] ?? ""),
});

interface HorizontalBarChartProps {
  labels: string[];
  data: number[];
  tone?: "primary" | "info" | "intel" | "critical" | "warning" | "success";
}

export function HorizontalBarChart({ labels, data, tone = "primary" }: HorizontalBarChartProps) {
  const t = useChartTheme();
  const color = t[tone];
  return (
    <Bar
      data={{
        labels,
        datasets: [
          {
            data,
            backgroundColor: color,
            borderWidth: 0,
            borderRadius: 999,
            borderSkipped: false,
            barThickness: 14,
          },
        ],
      }}
      options={{
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            ...tooltipBase(t),
            callbacks: {
              label: (ctx: TooltipItem<"bar">) => ` ${ctx.parsed.x} articles`,
            },
          },
        },
        scales: {
          x: { grid: gridLine(t), border: { display: false }, ticks: { color: t.textDim, maxTicksLimit: 8 } },
          y: { grid: { display: false }, border: { display: false }, ticks: { color: t.textBright, font: { size: 12 } } },
        },
      }}
    />
  );
}

interface MultiLineSeries {
  label: string;
  data: number[];
}

interface MultiLineChartProps {
  labels: string[];
  series: MultiLineSeries[];
}

/** Beberapa line sekaligus 1 chart (sector/country/victim-country trend). */
export function MultiLineChart({ labels, series }: MultiLineChartProps) {
  const t = useChartTheme();
  const slots = assignCategorySlots(series.map((s) => s.label));
  return (
    <Line
      data={{
        labels,
        datasets: series.map((s, i) => {
          const color = t.series[slots[i]];
          return {
            label: s.label,
            data: s.data,
            borderColor: color,
            backgroundColor: color,
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 4,
            tension: 0,
          };
        }),
      }}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: legendBase(t, "line"),
          tooltip: { ...tooltipBase(t), mode: "index", intersect: false },
        },
        scales: {
          x: { grid: gridLine(t), border: { display: false }, ticks: dateTicks(t, labels) },
          y: { grid: gridLine(t), border: { display: false }, ticks: { color: t.textDim }, beginAtZero: true },
        },
      }}
    />
  );
}

interface StackedBarChartProps {
  labels: string[];
  series: MultiLineSeries[];
}

/** Bar stacked (news-type trend per bulan). */
export function StackedBarChart({ labels, series }: StackedBarChartProps) {
  const t = useChartTheme();
  const slots = assignCategorySlots(series.map((s) => s.label));
  return (
    <Bar
      data={{
        labels,
        datasets: series.map((s, i) => ({
          label: s.label,
          data: s.data,
          backgroundColor: t.series[slots[i]],
          borderWidth: 0,
        })),
      }}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: legendBase(t, "circle"),
          tooltip: tooltipBase(t),
        },
        scales: {
          x: { stacked: true, grid: { display: false }, border: { display: false }, ticks: dateTicks(t, labels) },
          y: { stacked: true, grid: gridLine(t), border: { display: false }, ticks: { color: t.textDim } },
        },
      }}
    />
  );
}

interface TAActivityTimelineChartProps {
  labels: string[];
  articleCounts: number[];
  tweetCounts: number[];
  ransomCounts: number[];
}

/** Port `_tapLoadTimeline()`'s Chart.js config (`ta.js:740-763`) -- 3
 * series stacked+filled (Articles/Tweets/Ransom), dipakai Threat Actor
 * Room Grup G6. */
export function TAActivityTimelineChart({ labels, articleCounts, tweetCounts, ransomCounts }: TAActivityTimelineChartProps) {
  const t = useChartTheme();
  return (
    <Line
      data={{
        labels,
        datasets: [
          { label: "Articles", data: articleCounts, borderColor: withAlpha(t.primary, 0.8), backgroundColor: withAlpha(t.primary, 0.15), fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 4 },
          { label: "Tweets", data: tweetCounts, borderColor: withAlpha(t.info, 0.8), backgroundColor: withAlpha(t.info, 0.1), fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 4 },
          { label: "Ransom", data: ransomCounts, borderColor: withAlpha(t.critical, 0.8), backgroundColor: withAlpha(t.critical, 0.1), fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 4 },
        ],
      }}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: legendBase(t, "line"),
          tooltip: tooltipBase(t),
        },
        scales: {
          x: { grid: gridLine(t), border: { display: false }, ticks: dateTicks(t, labels) },
          y: { grid: gridLine(t), border: { display: false }, ticks: { color: t.textDim }, beginAtZero: true, stacked: true },
        },
      }}
    />
  );
}

interface GradedDoughnutChartProps {
  counts: Record<string, number>;
}

/** Doughnut Source Reliability Spread -- warna per grade A-F (bukan
 * palet siklik `CHART_COLORS`), F/grade gak dikenal fallback abu-abu. */
export function GradedDoughnutChart({ counts }: GradedDoughnutChartProps) {
  const t = useChartTheme();
  const grades = Object.keys(counts).sort();
  return (
    <Doughnut
      data={{
        labels: grades.map((g) => `${g} – ${counts[g]}`),
        datasets: [
          {
            data: grades.map((g) => counts[g]),
            backgroundColor: grades.map((g) => t.grades[g] ?? t.textDim),
            borderColor: t.surface,
            borderWidth: 3,
            borderRadius: 6,
            hoverOffset: 8,
          },
        ],
      }}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "right",
            labels: { color: t.textDim, padding: 12, usePointStyle: true, pointStyle: "circle", boxWidth: 8, font: { size: 12 } },
          },
          tooltip: tooltipBase(t),
        },
        cutout: "68%",
      }}
    />
  );
}

interface TimelineChartProps {
  labels: string[];
  data: number[];
  /** Nama deret utama (tooltip/legenda); tanpa ini tooltip tetap "N articles" seperti sebelumnya. */
  label?: string;
  tone?: "primary" | "info" | "intel" | "critical";
  /** Deret kedua (mis. insiden terkonfirmasi di atas semua berita); legenda tampil bila ada. */
  secondary?: { label: string; data: number[]; tone?: "primary" | "info" | "intel" | "critical" };
  /** Titik terakhir digambar lebih besar (mis. minggu berjalan di kartu ransomware). */
  emphasizeLast?: boolean;
}

export function TimelineChart({
  labels,
  data,
  label,
  tone = "primary",
  secondary,
  emphasizeLast,
}: TimelineChartProps) {
  const t = useChartTheme();
  const color = t[tone];
  const radius = (n: number) => labels.map((_, i) => (emphasizeLast && i === labels.length - 1 ? 5 : n));
  return (
    <Line
      data={{
        labels,
        datasets: [
          {
            label,
            data,
            borderColor: color,
            backgroundColor: withAlpha(color, 0.06),
            borderWidth: 2,
            pointRadius: radius(0),
            pointHoverRadius: 4,
            pointBackgroundColor: color,
            fill: true,
            tension: 0,
          },
          ...(secondary
            ? [
                {
                  label: secondary.label,
                  data: secondary.data,
                  borderColor: t[secondary.tone ?? "primary"],
                  backgroundColor: withAlpha(t[secondary.tone ?? "primary"], 0.06),
                  borderWidth: 2,
                  pointRadius: radius(0),
                  pointHoverRadius: 4,
                  pointBackgroundColor: t[secondary.tone ?? "primary"],
                  fill: true,
                  tension: 0,
                },
              ]
            : []),
        ],
      }}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: secondary ? legendBase(t, "line") : { display: false },
          tooltip: {
            ...tooltipBase(t),
            callbacks: {
              label: (ctx: TooltipItem<"line">) =>
                secondary || label ? ` ${ctx.dataset.label}: ${ctx.parsed.y}` : ` ${ctx.parsed.y} articles`,
            },
          },
        },
        scales: {
          x: { grid: gridLine(t), border: { display: false }, ticks: dateTicks(t, labels) },
          y: { grid: gridLine(t), border: { display: false }, ticks: { color: t.textDim }, beginAtZero: true },
        },
      }}
    />
  );
}

const SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"] as const;

interface SeverityStackedChartProps {
  labels: string[];
  /** Jumlah per severity, panjang tiap array = `labels.length`. */
  counts: Record<(typeof SEVERITY_ORDER)[number], number[]>;
}

/** Kolom stacked per bulan, satu warna per severity (token `--severity-*`,
 * warna mengikuti ENTITAS severity, bukan urutan). Jarak 2px antar segmen
 * lewat border warna surface; tooltip menampilkan total bulan itu. */
export function SeverityStackedChart({ labels, counts }: SeverityStackedChartProps) {
  const t = useChartTheme();
  return (
    <Bar
      data={{
        labels,
        datasets: SEVERITY_ORDER.map((sev) => ({
          label: sev.charAt(0) + sev.slice(1).toLowerCase(),
          data: counts[sev],
          backgroundColor: t.severity[sev],
          borderColor: t.surface,
          borderWidth: 2,
          borderSkipped: false as const,
        })),
      }}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            position: "bottom",
            labels: { color: t.textDim, boxWidth: 8, usePointStyle: true, pointStyle: "circle", font: { size: 12 } },
          },
          tooltip: {
            ...tooltipBase(t),
            callbacks: {
              footer: (items: TooltipItem<"bar">[]) => `Total: ${items.reduce((sum, i) => sum + (i.parsed.y ?? 0), 0)}`,
            },
          },
        },
        scales: {
          x: { stacked: true, grid: { display: false }, border: { display: false }, ticks: { color: t.textDim } },
          y: {
            stacked: true,
            beginAtZero: true,
            grid: gridLine(t),
            border: { display: false },
            ticks: { color: t.textDim, precision: 0 },
          },
        },
      }}
    />
  );
}
