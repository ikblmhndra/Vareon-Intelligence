"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { useDebounced } from "@/lib/cve/catalog";
import { errorMessage } from "@/lib/newsletter/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TabPills, type TabPillItem } from "@/components/ui/tab-pills";
import { SimplePager, usePageResetOn } from "@/components/pager";
import { PanelEmpty, PanelError, PanelLoading, PanelShell } from "@/components/newsroom/panel-shell";
import { useCan } from "@/lib/auth/permissions";

const PAGE_SIZE = 20;
const QUERY_KEY = ["newsroom", "filtered"] as const;

type Kind = "unrelated" | "failed";

const KIND_TABS: TabPillItem<Kind>[] = [
  { value: "unrelated", label: "Not cyber-related" },
  { value: "failed", label: "Failed enrichment", tone: "destructive" },
];

const HINT: Record<Kind, string> = {
  unrelated:
    "Articles the LLM classified as not cyber-related. Restore adds one to the news feed without enrichment (no countries, actors or TTPs).",
  failed:
    "Articles that could not be processed (LLM or network error), so they are not in the news feed yet. Fix the cause, then Replay re-runs the full pipeline; the row disappears once the article is processed.",
};

/** Sub-view admin "Filtered Articles" (`rejected_articles`): dua jenis baris yang dulu bercampur --
 * ditolak klasifikasi LLM (`failure_kind` null, bisa Restore) dan enrichment GAGAL (bisa Replay).
 * Di-gate admin di halaman (`page.tsx`); Replay juga admin-only di API. */
export function FilteredView() {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<Kind>("unrelated");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounced(search);
  const [page, setPage] = usePageResetOn(`${kind}|${debouncedSearch}`);

  const query = useQuery({
    queryKey: [...QUERY_KEY, kind, debouncedSearch, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/filtered-articles", {
        params: { query: { page, page_size: PAGE_SIZE, search: debouncedSearch || undefined, kind } },
      });
      if (error) throw error;
      return data;
    },
  });

  const restoreMutation = useMutation({
    mutationFn: async (id: number) => {
      const { error, response } = await api.POST("/api/filtered-articles/{article_id}/restore", {
        params: { path: { article_id: id } },
      });
      if (!response.ok) throw new Error(errorMessage(error));
    },
    onSuccess: () => {
      toast.success("Restored to the news feed");
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: (e: Error) => toast.error(`Restore failed: ${e.message}`),
  });

  const replayMutation = useMutation({
    mutationFn: async (id: number) => {
      const { error, response } = await api.POST("/api/filtered-articles/{article_id}/replay", {
        params: { path: { article_id: id } },
      });
      if (!response.ok) throw new Error(errorMessage(error));
    },
    onSuccess: () => {
      toast.success("Replay queued. The article appears in the news feed once processed.");
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: (e: Error) => toast.error(`Replay failed: ${e.message}`),
  });

  const totalPages = query.data ? Math.ceil(query.data.total / PAGE_SIZE) : 0;
  const mutation = kind === "failed" ? replayMutation : restoreMutation;
  const actionLabel = kind === "failed" ? "Replay" : "Restore";
  const can = useCan();
  const canAct = kind === "failed" ? can("manage_scraper") : can("manage_sources");

  return (
    <div className="mx-auto max-w-3xl">
      {/* Masthead (h1 "Newsroom") tidak tampil di tab ini; halaman tetap butuh satu h1. */}
      <h1 className="sr-only">Filtered Articles</h1>
      <TabPills aria-label="Filtered article kinds" className="mb-3" items={KIND_TABS} value={kind} onChange={setKind} />
      <PanelShell
        title={kind === "failed" ? "Failed enrichment" : "Not Related Cyber"}
        count={query.data?.total}
        onRefresh={() => query.refetch()}
        isRefreshing={query.isFetching}
        footer={<SimplePager page={page} totalPages={totalPages} onPageChange={setPage} />}
      >
        <div className="mb-2 flex items-center gap-2">
          <Input
            aria-label="Search title or source"
            placeholder="Search title or source…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-52 font-mono text-xs"
          />
        </div>
        <p className="mb-2 border-b border-border pb-2 text-xs text-muted-foreground">{HINT[kind]}</p>

        {query.isPending && <PanelLoading />}
        {query.isError && <PanelError />}
        {query.data && query.data.items.length === 0 && (
          <PanelEmpty message={kind === "failed" ? "No failed enrichments" : "No filtered articles"} />
        )}
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
                  <div className="mt-1 flex flex-wrap items-center gap-2 font-mono text-xs text-muted-foreground">
                    <span>{(a.rejected_at ?? "").slice(0, 10)}</span>
                    <span>{a.source}</span>
                    {a.posted_on && <span>posted {a.posted_on}</span>}
                    {a.failure_kind && (
                      <span className="rounded-full border border-warning/30 bg-warning/10 px-2 text-warning-text">
                        {a.failure_kind}
                      </span>
                    )}
                  </div>
                  {a.reason && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{a.reason}</p>}
                </div>
                {canAct && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="shrink-0"
                    aria-label={`${actionLabel} ${a.title}`}
                    disabled={mutation.isPending && mutation.variables === a.id}
                    onClick={() => mutation.mutate(a.id)}
                  >
                    {kind === "failed" ? "↻ Replay" : "↺ Restore"}
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </PanelShell>
    </div>
  );
}
