import type { components } from "@/lib/api/schema";

type Article = components["schemas"]["ArticleOut"];

/** Kode alasan kredibilitas (`score_reasons.credibility`, P6 3.1) -> teks Inggris. Satu-satunya
 * tempat pemetaan ini di web (spec bagian 6), dipakai tooltip chip dan modal artikel. */
const CREDIBILITY_TEXT: Record<string, string> = {
  official: "official source",
  corroborated_3: "3+ independent sources",
  corroborated_2: "2 independent sources",
  primary: "primary source",
  single_aggregator: "single aggregator source",
  ungraded: "source not graded",
  analyst: "set by analyst",
  cve: "CVE present",
  ioc: "IOC present",
  explicit_ttp: "explicit ATT&CK ID",
};

/** Kode sinyal prioritas (`score_reasons.priority[].code`) -> teks Inggris. */
const PRIORITY_TEXT: Record<string, string> = {
  confirmed_incident: "confirmed incident",
  kev: "KEV",
  poc: "public PoC",
  ttps: "TTPs",
  actor: "threat actor",
  corroboration: "more sources",
  pir_match: "PIR match",
  own_asset: "own asset",
};

/** Kode yang belum dikenal web (API lebih baru) ditampilkan apa adanya, bukan disembunyikan. */
export function describeCredibility(codes: string[]): string {
  return codes.map((c) => CREDIBILITY_TEXT[c] ?? c).join(", ");
}

export function describePriority(items: { code: string; points: number }[]): string {
  return items
    .map((i) => `${PRIORITY_TEXT[i.code] ?? i.code} ${i.points >= 0 ? "+" : ""}${i.points}`)
    .join(", ");
}

/** Warna chip PRIORITY dari skor mentah (C25): >= 90 destructive, >= 70 warning, selain itu info. */
export function priorityTone(score: number): "destructive" | "warning" | "info" {
  return score >= 90 ? "destructive" : score >= 70 ? "warning" : "info";
}

/** Label baris "Why it ranks first" per kode sinyal (spec 6.4, P16); kode tak dikenal dicetak apa adanya. */
export const PRIORITY_LINE: Record<string, (a: Article) => string> = {
  confirmed_incident: () => "Confirmed incident",
  kev: () => "On CISA KEV",
  poc: () => "Public proof of concept",
  ttps: (a) => (a.ttps.length > 0 ? `${a.ttps.length} ATT&CK techniques` : "ATT&CK techniques"),
  actor: () => "Named threat actor",
  corroboration: (a) =>
    a.story ? `Corroborated by ${a.story.source_count} sources` : "Corroborated by other sources",
  pir_match: (a) =>
    a.score_reasons.pir.length > 0
      ? `Matches your PIR: ${a.score_reasons.pir.map((p) => p.title).join(", ")}`
      : "Matches a PIR",
  own_asset: (a) =>
    a.score_reasons.own_asset.length > 0
      ? `Mentions your assets: ${a.score_reasons.own_asset.join(", ")}`
      : "Mentions your assets",
};

/** Urut points menurun; `sort` stabil menjaga urutan terima untuk poin yang sama. "−" (U+2212) untuk negatif. */
export function priorityLines(a: Article): string[] {
  return [...a.score_reasons.priority]
    .sort((x, y) => y.points - x.points)
    .map((i) => {
      const label = PRIORITY_LINE[i.code]?.(a) ?? i.code;
      return `${label} ${i.points < 0 ? "\u2212" : "+"}${Math.abs(i.points)}`;
    });
}

export type GradeFields = Pick<
  Article,
  | "admiralty_code"
  | "reliability_grade"
  | "credibility"
  | "grade_origin"
  | "confidence_score"
  | "priority_score"
  | "score_reasons"
>;

/** Baris penjelasan nilai artikel (spec bagian 6): reliabilitas sumber + asalnya, kredibilitas +
 * alasannya, confidence, rincian prioritas. Dipakai `title` chip dan bagian "Why this grade". */
export function gradeLines(a: GradeFields): string[] {
  const lines: string[] = [];
  if (a.reliability_grade) {
    lines.push(`Source reliability ${a.reliability_grade} (${a.grade_origin ?? "ungraded"})`);
  }
  if (a.credibility != null) {
    const why = describeCredibility(a.score_reasons.credibility);
    lines.push(`Credibility ${a.credibility}${why ? `: ${why}` : ""}`);
  }
  if (a.confidence_score != null) lines.push(`Confidence ${a.confidence_score}`);
  if (a.priority_score != null) {
    const why = describePriority(a.score_reasons.priority);
    lines.push(`Priority ${a.priority_score}${why ? `: ${why}` : ""}`);
  }
  return lines;
}
