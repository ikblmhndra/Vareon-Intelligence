/** Urutan daftar CVE (0.8.18): pilihan pengguna di kartu CVEs, selalu menurun (terbaru/tertinggi dulu).
 * Helper murni tanpa import (diuji `node --test`). Default `detected` = CVE yang baru ditemukan scraper di atas. */
export type CveSort = "detected" | "published" | "risk";

export const DEFAULT_CVE_SORT: CveSort = "detected";

export const CVE_SORT_OPTIONS: readonly { value: CveSort; label: string }[] = [
  { value: "detected", label: "detected" },
  { value: "published", label: "published" },
  { value: "risk", label: "risk" },
];

const SUBTITLE: Record<CveSort, string> = {
  detected: "detected date",
  published: "published date",
  risk: "risk",
};

/** Parameter `sort_by`/`sort_dir` untuk `GET /api/cve`. */
export function cveSortParams(sort: CveSort): { sort_by: CveSort; sort_dir: "desc" } {
  return { sort_by: sort, sort_dir: "desc" };
}

export function cveSortSubtitle(total: number, sort: CveSort): string {
  return `${total} ${total === 1 ? "CVE" : "CVEs"} - sorted by ${SUBTITLE[sort]}`;
}
