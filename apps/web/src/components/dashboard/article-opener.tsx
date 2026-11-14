"use client";

import { useState, type ReactNode } from "react";
import { ArticleModal } from "@/components/newsroom/article-modal";
import type { components } from "@/lib/api/schema";

type Article = components["schemas"]["ArticleOut"];

/** Hook pembuka `ArticleModal` untuk seksi Dashboard: panggil `openArticle`, render `host` sekali. */
export function useArticleOpener(): { openArticle: (a: Article) => void; host: ReactNode } {
  const [selected, setSelected] = useState<Article | null>(null);
  const host = (
    <ArticleModal
      article={selected}
      onOpenChange={(o) => {
        if (!o) setSelected(null);
      }}
    />
  );
  return { openArticle: setSelected, host };
}
