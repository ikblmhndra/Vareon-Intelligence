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
