"use client";

import type { components } from "@/lib/api/schema";
import type { NewsroomFilters } from "@/lib/newsroom/filters";
import { ArticleCollection } from "@/components/newsroom/article-card";
import { PanelEmpty, PanelError, PanelLoading, PanelShell } from "@/components/newsroom/panel-shell";
import { SimplePager, usePageResetOn } from "@/components/pager";
import { useArticlesQuery } from "@/components/newsroom/use-articles";

type Article = components["schemas"]["ArticleOut"];

const PAGE_SIZE = 15;

/**
 * Port `loadPanel('apac'|'global')`/`PANEL_CONFIG` (`cve.js` -- iya,
 * fungsi panel newsroom nangkring di file itu di app lama, bukan salah
 * taruh di sini). Newsroom lama newsType `global` sebenernya multi-value
 * (`['global', 'Security Technology & Best Practices', ...]`), diteruskan
 * apa adanya.
 */
export function NewsTypePanel({
  title,
  newsType,
  filters,
  onSelect,
}: {
  title: string;
  newsType: string[];
  filters: NewsroomFilters;
  onSelect: (a: Article) => void;
}) {
  const [page, setPage] = usePageResetOn(filters);

  const query = useArticlesQuery(
    ["news-type", newsType],
    {
      page,
      page_size: PAGE_SIZE,
      news_type: newsType,
      posted_on_start: filters.dateStart || undefined,
      posted_on_end: filters.dateEnd || undefined,
      country: filters.country ? [filters.country] : undefined,
      industry: filters.industry ? [filters.industry] : undefined,
      threat_actor: filters.actor ? [filters.actor] : undefined,
      search: filters.search || undefined,
    },
  );

  const totalPages = query.data ? Math.ceil(query.data.total / PAGE_SIZE) : 0;

  return (
    <PanelShell
      title={title}
      count={query.data?.total}
      onRefresh={() => query.refetch()}
      isRefreshing={query.isFetching}
      footer={<SimplePager page={page} totalPages={totalPages} onPageChange={setPage} />}
    >
      {query.isPending && <PanelLoading />}
      {query.isError && <PanelError />}
      {query.data && query.data.articles.length === 0 && <PanelEmpty message={`No ${title.toLowerCase()}`} />}
      {query.data && query.data.articles.length > 0 && (
        <ArticleCollection articles={query.data.articles} layout="list" onSelect={onSelect} />
      )}
    </PanelShell>
  );
}
