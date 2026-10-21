"use client";

import type { components } from "@/lib/api/schema";
import type { NewsroomFilters } from "@/lib/newsroom/filters";
import { useAuth } from "@/components/providers/auth-provider";
import { ArticleCollection } from "@/components/newsroom/article-card";
import { PanelEmpty, PanelError, PanelLoading, PanelShell } from "@/components/newsroom/panel-shell";
import { SimplePager, usePageResetOn } from "@/components/pager";
import { useArticlesQuery } from "@/components/newsroom/use-articles";

type Article = components["schemas"]["ArticleOut"];

const PAGE_SIZE = 15;

function localPanelTitle(countries: string[]): string {
  if (countries.length === 0) return "Global";
  if (countries.length === 1) return countries[0]!;
  return "Local";
}

/** Port `loadLocalPanel()` (`cve.js`) -- di-scope ke `client_countries`
 * user aktif (`AuthUser.client_countries`, sama data yang dipakai
 * `<ClientSwitcher>` Grup A), BUKAN filter country di filter bar (yang
 * malah diabaikan di panel ini, port asimetri apa adanya). */
export function LocalPanel({
  filters,
  onSelect,
}: {
  filters: NewsroomFilters;
  onSelect: (a: Article) => void;
}) {
  const { user } = useAuth();
  const countries = user?.client_countries ?? [];
  const [page, setPage] = usePageResetOn(filters);

  const query = useArticlesQuery(
    ["local", countries],
    {
      page,
      page_size: PAGE_SIZE,
      country: countries.length ? countries : undefined,
      posted_on_start: filters.dateStart || undefined,
      posted_on_end: filters.dateEnd || undefined,
      industry: filters.industry ? [filters.industry] : undefined,
      threat_actor: filters.actor ? [filters.actor] : undefined,
      search: filters.search || undefined,
    },
  );

  const totalPages = query.data ? Math.ceil(query.data.total / PAGE_SIZE) : 0;
  const title = localPanelTitle(countries);

  return (
    <PanelShell
      title={`${title} News`}
      count={query.data?.total}
      onRefresh={() => query.refetch()}
      isRefreshing={query.isFetching}
      minHeight
      footer={<SimplePager page={page} totalPages={totalPages} onPageChange={setPage} />}
    >
      {query.isPending && <PanelLoading />}
      {query.isError && <PanelError />}
      {query.data && query.data.articles.length === 0 && <PanelEmpty message="No local news" />}
      {query.data && query.data.articles.length > 0 && (
        <ArticleCollection articles={query.data.articles} layout="grid" onSelect={onSelect} />
      )}
    </PanelShell>
  );
}
