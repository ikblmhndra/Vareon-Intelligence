"use client";

import type { components } from "@/lib/api/schema";
import type { NewsroomFilters } from "@/lib/newsroom/filters";
import type { NewsroomUi } from "@/lib/newsroom/period";
import type { Narrowing } from "@/components/newsroom/newsroom-queries";

type Article = components["schemas"]["ArticleOut"];

/** Kerangka Task 3: props final, isi diisi Task 4. */
export function FrontPage(props: {
  ui: NewsroomUi;
  filters: NewsroomFilters;
  narrowing: Narrowing;
  onChange: (p: Partial<NewsroomUi>) => void;
  openArticle: (a: Article) => void;
  onOpenStory: (storyId: number, title: string) => void;
}) {
  void props;
  return null;
}
