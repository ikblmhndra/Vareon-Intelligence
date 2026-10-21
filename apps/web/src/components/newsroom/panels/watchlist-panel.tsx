"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { NewsroomFilters } from "@/lib/newsroom/filters";
import { ArticleCollection } from "@/components/newsroom/article-card";
import { PanelEmpty, PanelError, PanelLoading, PanelShell } from "@/components/newsroom/panel-shell";
import { SimplePager, usePageResetOn } from "@/components/pager";
import { useArticlesQuery } from "@/components/newsroom/use-articles";

type Article = components["schemas"]["ArticleOut"];

const PAGE_SIZE = 20;

function useWatchlistNames() {
  return useQuery({
    queryKey: ["ta", "watchlist-names"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/ta/watchlist-names");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return (data as { names?: string[] } | undefined)?.names ?? [];
    },
  });
}

/** Port `loadWatchlistPanel()` (`ta.js`) -- resolve nama TA watchlist dulu
 * (`GET /api/ta/watchlist-names`), baru query artikel by `threat_actor`.
 * Cuma respect filter `search` (BUKAN date/industry/actor/country), port
 * asimetri apa adanya. */
export function WatchlistPanel({
  filters,
  onSelect,
}: {
  filters: NewsroomFilters;
  onSelect: (a: Article) => void;
}) {
  const names = useWatchlistNames();
  const [page, setPage] = usePageResetOn(filters);

  const hasNames = (names.data?.length ?? 0) > 0;
  const query = useArticlesQuery(
    ["watchlist", names.data],
    {
      page,
      page_size: PAGE_SIZE,
      threat_actor: names.data,
      search: filters.search || undefined,
    },
    hasNames,
  );

  const totalPages = query.data ? Math.ceil(query.data.total / PAGE_SIZE) : 0;

  return (
    <PanelShell
      title="TA Watchlist News"
      count={hasNames ? query.data?.total : 0}
      onRefresh={() => query.refetch()}
      isRefreshing={query.isFetching}
      minHeight
      footer={hasNames && <SimplePager page={page} totalPages={totalPages} onPageChange={setPage} />}
    >
      {names.isPending && <PanelLoading />}
      {!names.isPending && !hasNames && (
        <PanelEmpty message="No threat actors in watchlist. Add via Threat Actor Room → Watchlist." />
      )}
      {hasNames && query.isPending && <PanelLoading />}
      {hasNames && query.isError && <PanelError />}
      {hasNames && query.data && query.data.articles.length === 0 && (
        <PanelEmpty message="No articles found for watched threat actors" />
      )}
      {hasNames && query.data && query.data.articles.length > 0 && (
        <ArticleCollection articles={query.data.articles} layout="grid" onSelect={onSelect} />
      )}
    </PanelShell>
  );
}
