"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SimplePager } from "@/components/pager";
import { PanelEmpty, PanelError, PanelLoading, PanelShell } from "@/components/newsroom/panel-shell";

const PAGE_SIZE = 20;
const QUERY_KEY = ["newsroom", "filtered"] as const;

/** Port sub-view "Not Related Cyber" (`newsroom-view-filtered`) --
 * artikel yang LLM tolak (`rejected_articles`), admin+ doang boleh liat
 * (di-gate di halaman, lihat `page.tsx`) sama `POST .../restore`
 * (`require_auth`, `GET` sendiri gak di-gate, port asimetri apa adanya). */
export function FilteredView() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const query = useQuery({
    queryKey: [...QUERY_KEY, search, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/filtered-articles", {
        params: { query: { page, page_size: PAGE_SIZE, search: search || undefined } },
      });
      if (error) throw error;
      return data;
    },
  });

  const restoreMutation = useMutation({
    mutationFn: async (id: number) => {
      const { response } = await api.POST("/api/filtered-articles/{article_id}/restore", {
        params: { path: { article_id: id } },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
  });

  const totalPages = query.data ? Math.ceil(query.data.total / PAGE_SIZE) : 0;

  return (
    <div className="mx-auto max-w-3xl">
      <PanelShell
        title="Not Related Cyber"
        count={query.data?.total}
        onRefresh={() => query.refetch()}
        isRefreshing={query.isFetching}
        footer={<SimplePager page={page} totalPages={totalPages} onPageChange={setPage} />}
      >
        <div className="mb-2 flex items-center gap-2">
          <Input
            placeholder="Search title or source…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && setPage(1)}
            className="w-52 font-mono text-xs"
          />
          <Button size="sm" onClick={() => setPage(1)}>
            Search
          </Button>
        </div>
        <p className="mb-2 border-b border-border pb-2 text-xs text-muted-foreground">
          Articles LLM classified as not cyber-related. Restore to re-queue through NLP pipeline.
        </p>

        {query.isPending && <PanelLoading />}
        {query.isError && <PanelError />}
        {query.data && query.data.items.length === 0 && <PanelEmpty message="No filtered articles" />}
        {query.data && query.data.items.length > 0 && (
          <div className="flex flex-col gap-1.5">
            {query.data.items.map((a) => (
              <div key={a.id} className="flex items-start gap-2.5 rounded-xl border border-border bg-background p-2.5">
                <div className="min-w-0 flex-1">
                  <a
                    href={a.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-foreground no-underline hover:text-primary"
                  >
                    {a.title}
                  </a>
                  <div className="mt-1 flex gap-2 font-mono text-xs text-muted-foreground">
                    <span>{(a.rejected_at ?? "").slice(0, 10)}</span>
                    <span>{a.source}</span>
                    {a.posted_on && <span>posted {a.posted_on}</span>}
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  className="shrink-0"
                  disabled={restoreMutation.isPending && restoreMutation.variables === a.id}
                  onClick={() => restoreMutation.mutate(a.id)}
                >
                  ↺ Restore
                </Button>
              </div>
            ))}
          </div>
        )}
      </PanelShell>
    </div>
  );
}
