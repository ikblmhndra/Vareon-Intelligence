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

function useTechStackNames() {
  return useQuery({
    queryKey: ["techstack", "names"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/techstack", { params: { query: { page_size: 500 } } });
      if (error) throw error;
      return data.items.map((t) => t.name);
    },
  });
}

/** Port `loadTechStackPanel()` (`ta.js`) -- resolve nama tech stack dulu
 * (`GET /api/techstack?page_size=500`), query artikel by `title_keyword`.
 * Respect date/industry/actor/search (BUKAN country), sama pola kayak
 * Local panel. */
export function TechStackPanel({
  filters,
  onSelect,
}: {
  filters: NewsroomFilters;
  onSelect: (a: Article) => void;
}) {
  const names = useTechStackNames();
  const [page, setPage] = usePageResetOn(filters);

  const hasNames = (names.data?.length ?? 0) > 0;
  const query = useArticlesQuery(
    ["techstack", names.data],
    {
      page,
      page_size: PAGE_SIZE,
      title_keyword: names.data,
      posted_on_start: filters.dateStart || undefined,
      posted_on_end: filters.dateEnd || undefined,
      industry: filters.industry ? [filters.industry] : undefined,
      threat_actor: filters.actor ? [filters.actor] : undefined,
      search: filters.search || undefined,
    },
    hasNames,
  );

  const totalPages = query.data ? Math.ceil(query.data.total / PAGE_SIZE) : 0;

  return (
    <PanelShell
      title="Tech Stack News"
      count={hasNames ? query.data?.total : 0}
      onRefresh={() => query.refetch()}
      isRefreshing={query.isFetching}
      minHeight
      footer={hasNames && <SimplePager page={page} totalPages={totalPages} onPageChange={setPage} />}
    >
      {names.isPending && <PanelLoading />}
      {!names.isPending && !hasNames && (
        <PanelEmpty message="No tech stack configured. Add via Tech Stack settings." />
      )}
      {hasNames && query.isPending && <PanelLoading />}
      {hasNames && query.isError && <PanelError />}
      {hasNames && query.data && query.data.articles.length === 0 && (
        <PanelEmpty message="No articles found for configured tech stack" />
      )}
      {hasNames && query.data && query.data.articles.length > 0 && (
        <ArticleCollection articles={query.data.articles} layout="grid" onSelect={onSelect} />
      )}
    </PanelShell>
  );
}
