"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { SubListSection, SUBLIST_PAGE_SIZE } from "@/components/entities/entity-subtab";
import { ArticleModal } from "@/components/newsroom/article-modal";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { relativeTime } from "@/lib/cve/freshness";

type EntityDetail = components["schemas"]["EntityDetail"];
type Article = components["schemas"]["ArticleOut"];

/** Story belum punya halaman sendiri: judulnya membuka artikel terbaru di story itu (modal Newsroom). */
export function EntityStoriesTab({ entity }: { entity: EntityDetail }) {
  const [page, setPage] = useState(1);
  const [article, setArticle] = useState<Article | null>(null);
  const [opening, setOpening] = useState<number | null>(null);

  const list = useQuery({
    queryKey: ["entity-stories", entity.id, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/entities/{entity_id}/stories", {
        params: {
          path: { entity_id: entity.id },
          query: { limit: SUBLIST_PAGE_SIZE, offset: (page - 1) * SUBLIST_PAGE_SIZE },
        },
      });
      if (error || !data) throw new Error("stories failed");
      return data;
    },
  });

  async function openStory(storyId: number) {
    setOpening(storyId);
    try {
      const { data, error } = await api.GET("/api/articles", {
        params: { query: { story_id: storyId, page_size: 1, dedup: false } },
      });
      const first = data?.articles[0];
      if (error || !first) throw new Error("no article");
      setArticle(first);
    } catch {
      toast.error("Could not open the story's article.");
    } finally {
      setOpening(null);
    }
  }

  return (
    <>
      <SubListSection
        id="entity-stories"
        title="Stories"
        status={list.status}
        total={list.data?.total ?? 0}
        emptyText="No stories mention this entity yet."
        page={page}
        onPageChange={setPage}
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Story</TableHead>
              <TableHead>Lead source</TableHead>
              <TableHead className="text-right">Articles</TableHead>
              <TableHead className="text-right">Sources</TableHead>
              <TableHead>Last seen</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.data?.items.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="max-w-md whitespace-normal">
                  <button
                    type="button"
                    disabled={opening === s.id}
                    onClick={() => void openStory(s.id)}
                    className="rounded text-left text-sm font-medium text-primary-text underline-offset-2 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-focus"
                  >
                    {s.title}
                  </button>
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">{s.lead_source}</TableCell>
                <TableCell className="text-right font-code text-xs">
                  {s.mentioned_articles}/{s.article_count}
                </TableCell>
                <TableCell className="text-right font-code text-xs">{s.source_count}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{relativeTime(s.last_seen_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </SubListSection>
      <ArticleModal article={article} onOpenChange={(o) => !o && setArticle(null)} />
    </>
  );
}
