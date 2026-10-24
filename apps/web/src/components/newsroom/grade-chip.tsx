import type { components } from "@/lib/api/schema";

type Article = components["schemas"]["ArticleOut"];

/** Chip confidence artikel: kode Admiralty sumber + skor ("B2 · 72"); tanpa kode jatuh ke "Score n". */
export function GradeChip({ a }: { a: Pick<Article, "admiralty_code" | "grade_origin" | "confidence_score"> }) {
  if (a.confidence_score == null) return null;
  if (!a.admiralty_code) return <span>Score {a.confidence_score}</span>;
  const origin = a.grade_origin ?? "default";
  return (
    <span title={`Source grade ${a.admiralty_code} (${origin})`}>
      {a.admiralty_code} · {a.confidence_score}
    </span>
  );
}
