import type { NewsletterSummaryMeta } from "@/lib/api/loose-types";
import { formatRange } from "@/lib/recap/period";

/**
 * Executive Summary (ROADMAP #22, PR 9): dari `summary_text` saran ke isi field intro, dan status
 * ringkasan yang dibaca dari `summary_meta`. Murni, tanpa React.
 */

/** Penanda yang ditulis server (`newsletter_summary.CVE_MARKER`) menggantikan CVE yang tidak ada di
 * recap sumbernya. Analis harus mengganti atau menghapusnya sebelum draft dibuat. */
export const CVE_MARKER = "[CVE tidak terverifikasi]";

export function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/**
 * `summary_text` (teks biasa) -> HTML untuk field intro: di-escape, satu `<p>` per paragraf.
 * `custom_intro` adalah HTML dan template merendernya apa adanya, jadi teks dari model TIDAK boleh
 * masuk mentah (karakter `<` atau `&` merusak atau menyisipkan markup). Kosong tetap kosong.
 */
export function summaryToIntro(text: string): string {
  const paragraphs = text
    .split(/\n\s*\n/)
    .map((p) => p.replace(/\s*\n\s*/g, " ").trim())
    .filter(Boolean);
  return paragraphs.map((p) => `<p>${escapeHtml(p)}</p>`).join("\n");
}

export function countCveMarkers(text: string): number {
  return text.split(CVE_MARKER).length - 1;
}

/** Indeks awal penanda berikutnya setelah `from` (melingkar ke awal), atau -1 kalau tidak ada. */
export function nextMarkerIndex(text: string, from: number): number {
  const after = text.indexOf(CVE_MARKER, from);
  return after !== -1 ? after : text.indexOf(CVE_MARKER);
}

export type SummaryStatus =
  | { kind: "ok" }
  /** Tidak ada recap mingguan yang menyentuh bulan itu, jadi tidak ada panggilan model. */
  | { kind: "no_recaps" }
  /** Model membalas tapi tanpa paragraf yang bisa dipakai. */
  | { kind: "parse_failed" }
  /** Panggilan model gagal (gateway mati, kunci salah, timeout). `error` = nama exception saja. */
  | { kind: "llm_error"; error: string }
  /** Kosong tanpa sebab yang tercatat (baris dari sebelum PR 8). */
  | { kind: "empty" };

/** Urutan memilih sengaja: `error` dan `parse_failed` lebih spesifik dari "kosong", dan
 * `no_recaps` hanya berlaku kalau model memang tidak dipanggil. */
export function summaryStatus(summaryText: string, meta: NewsletterSummaryMeta): SummaryStatus {
  if (meta.error) return { kind: "llm_error", error: meta.error };
  if (meta.parse_failed) return { kind: "parse_failed" };
  if (meta.token_usage?.skipped && meta.token_usage.reason === "no_recaps") return { kind: "no_recaps" };
  if (!summaryText.trim()) return { kind: "empty" };
  return { kind: "ok" };
}

/** Pekan yang dipakai ringkasan, mis. `["28 Sep - 4 Oct", "5 Oct - 11 Oct"]`. */
export function weekLabels(meta: NewsletterSummaryMeta): string[] {
  return (meta.weeks ?? []).map((w) => formatRange(w.week_start, w.week_end));
}

/** Hari yang tidak diliput ringkasan, mis. `["30 Nov"]`. */
export function uncoveredLabels(meta: NewsletterSummaryMeta): string[] {
  return (meta.uncovered ?? []).map((g) => formatRange(g.start, g.end));
}

/** Rentang yang diliput pekan-pekan itu, mis. `"28 Sep - 1 Nov"`; null tanpa recap. */
export function coveredLabel(meta: NewsletterSummaryMeta): string | null {
  return meta.covered_start && meta.covered_end ? formatRange(meta.covered_start, meta.covered_end) : null;
}
