"use client";

import type { components } from "@/lib/api/schema";
import type { NewsroomFilters } from "@/lib/newsroom/filters";
import type { RubricKey } from "@/components/newsroom/rubric-queries";

type Article = components["schemas"]["ArticleOut"];

/** Kerangka Task 3: props final, isi diisi Task 6. */
export function RubricGrid(props: {
  filters: NewsroomFilters;
  rubric: RubricKey | null;
  openArticle: (a: Article) => void;
  onSeeAll: (key: RubricKey) => void;
}) {
  void props;
  return null;
}
