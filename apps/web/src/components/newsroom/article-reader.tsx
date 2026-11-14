"use client";

import type { components } from "@/lib/api/schema";

type Article = components["schemas"]["ArticleOut"];

/** Stub Task 5; Task 8 mengisi pembaca. `listArticles` = baris daftar yang sudah dimuat (untuk
 * langkah sebelumnya/berikutnya), `onStep` memindahkan `article`. Props sudah final. */
export function ArticleReader(_props: {
  articleId: number | null;
  listArticles: Article[];
  onStep: (id: number) => void;
}) {
  return null;
}
