"use client";

import { useMemo, useSyncExternalStore } from "react";

/** Chart.js/canvas tidak bisa resolve `var(--x)`; baca nilai token dari
 * `<html>` dan re-render saat kelas tema (`dark`) berubah. */
function subscribe(cb: () => void) {
  const mo = new MutationObserver(cb);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => mo.disconnect();
}
const snapshot = () => document.documentElement.className;
const serverSnapshot = () => "";

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** `#rrggbb` -> `rgba(r,g,b,a)`; selain hex dikembalikan apa adanya. */
export function withAlpha(color: string, alpha: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(color);
  if (!m) return color;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

export interface ChartTheme {
  border: string;
  textDim: string;
  textBright: string;
  surface: string;
  primary: string;
  info: string;
  critical: string;
  warning: string;
  success: string;
  /** 10 warna siklik (doughnut/multi-series). */
  series: string[];
  grades: Record<string, string>;
  /** Warna per severity CVE (token `--severity-*`, sudah dipilih per tema). */
  severity: Record<"CRITICAL" | "HIGH" | "MEDIUM" | "LOW", string>;
}

/** Berubah tiap kelas tema `<html>` berubah; pakai sebagai dependency re-render. */
export function useThemeKey(): string {
  return useSyncExternalStore(subscribe, snapshot, serverSnapshot);
}

export function useChartTheme(): ChartTheme {
  const themeKey = useThemeKey();
  return useMemo(() => {
    void themeKey;
    const v = cssVar;
    return {
      border: v("--border"),
      textDim: v("--muted-foreground"),
      textBright: v("--foreground"),
      surface: v("--surface"),
      primary: v("--primary"),
      info: v("--info"),
      critical: v("--severity-critical"),
      warning: v("--warning"),
      success: v("--success"),
      series: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((i) => v(`--chart-${i}`)),
      grades: {
        A: v("--success"),
        B: v("--info"),
        C: v("--severity-medium"),
        D: v("--severity-high"),
        E: v("--severity-critical"),
        F: v("--muted-foreground"),
      },
      severity: {
        CRITICAL: v("--severity-critical"),
        HIGH: v("--severity-high"),
        MEDIUM: v("--severity-medium"),
        LOW: v("--severity-low"),
      },
    };
  }, [themeKey]);
}
