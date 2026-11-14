export type PeriodKey = "1" | "7" | "30" | "90" | "all";

/** Lima periode Dashboard (spec 6.1). `days` ke API (null = semua waktu); `words` untuk kalimat,
 * `suffix` untuk akhir headline. */
export const PERIODS: readonly {
  key: PeriodKey;
  label: string;
  days: number | null;
  words: string;
  suffix: string;
}[] = [
  { key: "1", label: "24h", days: 1, words: "24 hours", suffix: "since yesterday" },
  { key: "7", label: "7d", days: 7, words: "7 days", suffix: "in the last 7 days" },
  { key: "30", label: "30d", days: 30, words: "30 days", suffix: "in the last 30 days" },
  { key: "90", label: "90d", days: 90, words: "90 days", suffix: "in the last 90 days" },
  { key: "all", label: "All", days: null, words: "all time", suffix: "of all time" },
];

export function periodInfo(key: PeriodKey) {
  return PERIODS.find((p) => p.key === key) ?? PERIODS[1];
}

/** Nilai `?period=` apa pun selain 1/30/90/all jatuh ke default "7" (URL tidak dipercaya). */
export function parsePeriod(value: string | null): PeriodKey {
  return value === "1" || value === "30" || value === "90" || value === "all" ? value : "7";
}

/** URL dengan `period` diganti; "7" (default) dihapus supaya URL bersih. Param lain dipertahankan. */
export function periodHref(pathname: string, searchParams: URLSearchParams, key: PeriodKey): string {
  const next = new URLSearchParams(searchParams);
  if (key === "7") next.delete("period");
  else next.set("period", key);
  const qs = next.toString();
  return pathname + (qs ? "?" + qs : "");
}
