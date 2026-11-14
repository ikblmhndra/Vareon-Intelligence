"use client";

import Link from "next/link";
import { useMemo } from "react";

import { PanelError } from "@/components/dashboard/stat-box";
import { articleWhen } from "@/components/dashboard/use-dashboard-overview";
import { useAllArticles, useAllListQuery } from "@/components/newsroom/all-articles-queries";
import { useRelatedArticles, useVictimRows } from "@/components/newsroom/all-articles-queries";
import { GradeChip } from "@/components/newsroom/grade-chip";
import { PriorityChip } from "@/components/newsroom/priority-chip";
import { useArticleMatchers } from "@/components/newsroom/rubric-queries";
import { Button } from "@/components/ui/button";
import { LoadMoreFooter } from "@/components/ui/load-more-footer";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SelectableList } from "@/components/ui/selectable-list";
import { Skeleton } from "@/components/ui/skeleton";
import type { components } from "@/lib/api/schema";
import type { RansomwareVictim } from "@/lib/api/loose-types";
import { countryName } from "@/lib/countries";
import { fmtShortDate } from "@/lib/format";
import type { AllState } from "@/lib/newsroom/all-state";

type Article = components["schemas"]["ArticleOut"];

const FOCUS =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

const SORT_ITEMS = { priority: "Sort: Priority", recent: "Sort: Recent" } as const;

/** "Reset filters": semua filter URL kembali ke default, `view` dan `article` tidak disentuh
 * (spec 6.2). Nilai default sama dengan yang dihilangkan `allStateToParams`. */
const RESET_PATCH: Partial<AllState> = {
  period: "7",
  from: null,
  countries: [],
  sector: null,
  sources: [],
  grades: [],
  rubric: null,
  actors: [],
  ttps: [],
  story: null,
  sort: "priority",
  q: "",
  incidents: false,
  group: null,
  vindustry: null,
};

function SkeletonRows() {
  return (
    <div aria-hidden className="flex flex-col gap-2">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <Skeleton key={i} className="h-16 w-full" />
      ))}
    </div>
  );
}

function ArticleRow({
  a,
  fetchedAt,
  labels,
}: {
  a: Article;
  fetchedAt: number;
  labels: { watchlist: boolean; techstack: boolean };
}) {
  const when = articleWhen(a, fetchedAt, true);
  const tags = [
    ...(a.news_type ? [a.news_type.toUpperCase()] : []),
    ...(labels.watchlist ? ["WATCHLIST"] : []),
    ...(labels.techstack ? ["TECH STACK"] : []),
  ];
  const extra = a.story && a.story.source_count > 1 ? ` +${a.story.source_count - 1}` : "";
  return (
    <span className="flex min-w-0 flex-col gap-1">
      <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-2xs font-semibold text-muted-foreground">
        {a.priority_score != null && <PriorityChip score={a.priority_score} />}
        {tags.map((t) => (
          <span key={t}>{t}</span>
        ))}
      </span>
      <span className="line-clamp-2 text-sm font-semibold leading-snug text-foreground">{a.title}</span>
      <span className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="min-w-0 truncate" title={when.title}>
          {a.source}
          {extra}
          {" · "}
          {when.text}
        </span>
        <GradeChip a={a} codeOnly />
      </span>
    </span>
  );
}

function VictimRow({ v }: { v: RansomwareVictim }) {
  const meta = [
    v.industry,
    v.country_code ? countryName(v.country_code) : null,
    fmtShortDate(v.published ?? v.discovered),
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className="rounded-[10px] px-3 py-2.5">
      <div className="text-sm font-semibold leading-snug text-foreground">
        {v.post_url ? (
          <a
            href={v.post_url}
            target="_blank"
            rel="noopener noreferrer"
            className={`rounded-sm hover:text-primary-text hover:underline ${FOCUS}`}
          >
            {v.victim}
          </a>
        ) : (
          v.victim
        )}
        {" · "}
        <span className="font-normal text-muted-foreground">{v.group_name}</span>
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">{meta}</div>
    </li>
  );
}

/** Kolom tengah All articles (spec 6.3). Query daftar dibangun hanya lewat `useAllListQuery` +
 * `useAllArticles`, pasangan yang sama dengan AllArticlesView, jadi keduanya berbagi satu entri
 * cache; kunci infinite query memuat seluruh filter, jadi ganti filter setelah "Load more" kembali
 * ke halaman 1 (tidak menempel baris filter lama). */
export function AllList({
  state,
  onChange,
  selected,
  onSelect,
}: {
  state: AllState;
  onChange: (patch: Partial<AllState>) => void;
  selected: number | null;
  onSelect: (id: number) => void;
}) {
  const { plan, query } = useAllListQuery(state);
  const list = useAllArticles(query);
  const isVictims = plan === "victims";
  // Rubrik Ransomware sudah di-null-kan induk tanpa `view_intel`; query hanya jalan untuk "victims".
  const victims = useVictimRows(state, isVictims);
  const related = useRelatedArticles(state, isVictims);
  const matchers = useArticleMatchers();

  const articles = useMemo(() => list.data?.pages.flatMap((p) => p.articles) ?? [], [list.data]);
  const victimRows = useMemo(() => victims.data?.pages.flatMap((p) => p.victims) ?? [], [victims.data]);
  const relatedRows = useMemo(() => related.data?.pages.flatMap((p) => p.articles) ?? [], [related.data]);
  const selectedKey = selected === null ? null : String(selected);

  // `story` memaksa recent (aturan 5); judul mengikuti urutan yang benar-benar dipakai.
  const sort = state.story !== null ? "recent" : state.sort;

  const resetButton = (
    <Button variant="outline" size="sm" onClick={() => onChange(RESET_PATCH)}>
      Reset filters
    </Button>
  );

  const header = (text: string, withSort: boolean) => (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="font-heading text-sm font-semibold">{text}</h2>
      {withSort && (
        <Select
          items={SORT_ITEMS}
          value={sort}
          onValueChange={(v) => {
            if (v === "priority" || v === "recent") onChange({ sort: v });
          }}
        >
          <SelectTrigger aria-label="Sort articles" className="w-40 text-xs" disabled={state.story !== null}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="priority" className="text-xs">
              Sort: Priority
            </SelectItem>
            <SelectItem value="recent" className="text-xs">
              Sort: Recent
            </SelectItem>
          </SelectContent>
        </Select>
      )}
    </div>
  );

  if (plan === "pending") {
    return (
      <div className="space-y-3">
        {header("Loading…", true)}
        <SkeletonRows />
      </div>
    );
  }

  if (plan === "no-names") {
    return (
      <div className="space-y-3">
        {header("0 articles match", true)}
        <p className="text-sm text-muted-foreground">
          {state.rubric === "watchlist" ? (
            "No watched actors yet."
          ) : (
            <>
              No tech stack yet.{" "}
              <Link href="/cve" className={`rounded text-primary-text hover:underline ${FOCUS}`}>
                Set up tech stack
              </Link>
            </>
          )}
        </p>
      </div>
    );
  }

  if (plan === "empty") {
    return (
      <div className="space-y-3">
        {header(sort === "priority" ? "0 stories match" : "0 articles match", true)}
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm text-muted-foreground">No articles match these filters.</p>
          {resetButton}
        </div>
      </div>
    );
  }

  if (isVictims) {
    const total = victims.data?.pages.at(-1)?.total;
    return (
      <div className="space-y-6">
        <section aria-label="Ransomware victims" className="space-y-3">
          {header(total === undefined ? "Victims" : `${total.toLocaleString("en-US")} victims match`, false)}
          {victims.isPending ? (
            <SkeletonRows />
          ) : victims.isError && !victims.data ? (
            <PanelError
              title="Could not load the victims"
              error={victims.error}
              onRetry={() => void victims.refetch()}
            />
          ) : victimRows.length === 0 ? (
            <div className="flex flex-col items-start gap-2">
              <p className="text-sm text-muted-foreground">No victims match these filters.</p>
              {resetButton}
            </div>
          ) : (
            <>
              <ul className={victims.isPlaceholderData ? "opacity-60" : undefined}>
                {victimRows.map((v) => (
                  <VictimRow key={v.id} v={v} />
                ))}
              </ul>
              <LoadMoreFooter
                shown={victimRows.length}
                total={total ?? victimRows.length}
                onLoadMore={() => void victims.fetchNextPage()}
                loading={victims.isFetchingNextPage}
                hasMore={victims.hasNextPage}
              />
            </>
          )}
        </section>
        <section aria-label="Related articles" className="space-y-3">
          <h2 className="font-heading text-sm font-semibold">Related articles</h2>
          {related.isPending ? (
            <SkeletonRows />
          ) : related.isError && !related.data ? (
            <PanelError
              title="Could not load the related articles"
              error={related.error}
              onRetry={() => void related.refetch()}
            />
          ) : relatedRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">No related ransomware articles yet.</p>
          ) : (
            <>
              <SelectableList
                aria-label="Related articles"
                items={relatedRows.map((a) => ({ value: String(a.id), a }))}
                value={selectedKey}
                onChange={(v) => onSelect(Number(v))}
                renderItem={({ a }) => <ArticleRow a={a} fetchedAt={related.dataUpdatedAt} labels={matchers(a)} />}
              />
              <LoadMoreFooter
                shown={relatedRows.length}
                total={related.data?.pages.at(-1)?.total ?? relatedRows.length}
                onLoadMore={() => void related.fetchNextPage()}
                loading={related.isFetchingNextPage}
                hasMore={related.hasNextPage}
              />
            </>
          )}
        </section>
      </div>
    );
  }

  const total = list.data?.pages.at(-1)?.total;
  const noun = sort === "priority" ? "stories" : "articles";
  return (
    <div className="space-y-3">
      {header(total === undefined ? "Articles" : `${total.toLocaleString("en-US")} ${noun} match`, true)}
      {list.isPending ? (
        <SkeletonRows />
      ) : list.isError && !list.data ? (
        <PanelError title="Could not load the articles" error={list.error} onRetry={() => void list.refetch()} />
      ) : articles.length === 0 ? (
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm text-muted-foreground">No articles match these filters.</p>
          {resetButton}
        </div>
      ) : (
        <div className={list.isPlaceholderData ? "opacity-60" : undefined}>
          <SelectableList
            aria-label="Articles"
            items={articles.map((a) => ({ value: String(a.id), a }))}
            value={selectedKey}
            onChange={(v) => onSelect(Number(v))}
            renderItem={({ a }) => <ArticleRow a={a} fetchedAt={list.dataUpdatedAt} labels={matchers(a)} />}
          />
          <LoadMoreFooter
            shown={articles.length}
            total={total ?? articles.length}
            onLoadMore={() => void list.fetchNextPage()}
            loading={list.isFetchingNextPage}
            hasMore={list.hasNextPage}
          />
        </div>
      )}
    </div>
  );
}
