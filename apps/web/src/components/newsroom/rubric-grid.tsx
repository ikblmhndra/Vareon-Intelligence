"use client";

import Link from "next/link";

import { PanelError } from "@/components/dashboard/stat-box";
import { articleWhen } from "@/components/dashboard/use-dashboard-overview";
import { GradeChip } from "@/components/newsroom/grade-chip";
import {
  useRubric,
  useTechStackNames,
  useWatchlistNames,
  type RubricItem,
  type RubricKey,
} from "@/components/newsroom/rubric-queries";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";
import { countryName } from "@/lib/dashboard/countries";
import { fmtShortDate, parseLocalDate } from "@/lib/format";
import type { NewsroomFilters } from "@/lib/newsroom/filters";

type Article = components["schemas"]["ArticleOut"];

const FOCUS =
  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none";

const COLUMNS: { key: RubricKey; title: string }[] = [
  { key: "apac", title: "APAC" },
  { key: "global", title: "Global" },
  { key: "local", title: "Local" },
  { key: "ransomware", title: "Ransomware victims" },
  { key: "watchlist", title: "Watchlist" },
  { key: "techstack", title: "Tech stack" },
];

function VictimRow({ item }: { item: RubricItem }) {
  const v = item.victim!;
  const second = [
    v.industry,
    v.country_code ? countryName(v.country_code) : null,
    v.published ? fmtShortDate(parseLocalDate(v.published.slice(0, 10))) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <>
      <div className="text-sm font-semibold text-foreground">
        {item.href ? (
          <a
            href={item.href}
            target="_blank"
            rel="noopener noreferrer"
            className={`rounded hover:underline ${FOCUS}`}
          >
            {v.victim}
          </a>
        ) : (
          v.victim
        )}
        {v.group_name && <span className="font-normal text-muted-foreground"> · {v.group_name}</span>}
      </div>
      {second && <div className="mt-0.5 text-xs text-muted-foreground">{second}</div>}
    </>
  );
}

function ArticleRow({
  item,
  updatedAt,
  openArticle,
}: {
  item: RubricItem;
  updatedAt: number;
  openArticle: (a: Article) => void;
}) {
  const a = item.article!;
  const when = articleWhen(a, updatedAt, true);
  return (
    <>
      <button
        type="button"
        onClick={() => openArticle(a)}
        className={`line-clamp-2 rounded text-left text-sm font-semibold text-foreground hover:underline ${FOCUS}`}
      >
        {a.title}
      </button>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
        <span>{a.source}</span>
        <span aria-hidden>·</span>
        <span title={when.title}>{when.text}</span>
        <GradeChip a={a} codeOnly />
      </div>
    </>
  );
}

function RubricColumn({
  rkey,
  title,
  filters,
  narrowed,
  openArticle,
  onSeeAll,
}: {
  rkey: RubricKey;
  title: string;
  filters: NewsroomFilters;
  narrowed: boolean;
  openArticle: (a: Article) => void;
  onSeeAll: (key: RubricKey) => void;
}) {
  const size = narrowed ? 9 : 3;
  const { items, total, updatedAt, isPending, isError, error, refetch } = useRubric(rkey, filters, 1, size);
  // Query nama dipakai bersama useRubric (key sama), jadi tidak ada request tambahan; hanya untuk
  // membedakan "belum ada nama" dari "periode kosong".
  const watch = useWatchlistNames(rkey === "watchlist");
  const tech = useTechStackNames(rkey === "techstack");
  const noNames =
    (rkey === "watchlist" && watch.isSuccess && watch.data.length === 0) ||
    (rkey === "techstack" && tech.isSuccess && tech.data.length === 0);

  return (
    <Card className="px-5" aria-labelledby={`rubric-${rkey}`}>
      <div className="flex items-baseline justify-between gap-2">
        <h3 id={`rubric-${rkey}`} className="text-base font-semibold text-foreground">
          {title}
          {total !== undefined && (
            <span className="ml-2 font-code text-xs font-normal text-muted-foreground">
              {total.toLocaleString("en-US")}
            </span>
          )}
        </h3>
        <button
          type="button"
          onClick={() => onSeeAll(rkey)}
          className={`rounded text-xs font-medium text-primary-text hover:underline ${FOCUS}`}
        >
          See all →
        </button>
      </div>
      {isPending ? (
        <div aria-hidden className="flex flex-col gap-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : isError && items.length === 0 ? (
        <PanelError title={`Could not load ${title}`} error={error} onRetry={refetch} />
      ) : items.length === 0 ? (
        <div className="text-sm text-muted-foreground">
          {noNames && rkey === "watchlist" ? (
            "No watched actors yet."
          ) : noNames ? (
            <>
              No tech stack yet.{" "}
              <Link href="/cve" className={`rounded text-primary-text hover:underline ${FOCUS}`}>
                Set up tech stack
              </Link>
            </>
          ) : (
            "Nothing in this period."
          )}
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {items.slice(0, size).map((item) => (
            <li key={item.id} className="py-2.5 first:pt-0 last:pb-0">
              {item.victim ? (
                <VictimRow item={item} />
              ) : (
                <ArticleRow item={item} updatedAt={updatedAt} openArticle={openArticle} />
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function RubricGrid({
  filters,
  rubric,
  openArticle,
  onSeeAll,
}: {
  filters: NewsroomFilters;
  rubric: RubricKey | null;
  openArticle: (a: Article) => void;
  onSeeAll: (key: RubricKey) => void;
}) {
  const can = useCan();
  // P6: tanpa izin kolom tidak dirender, jadi hook-nya tidak jalan dan tidak ada request 403.
  // `/api/ransomware/*` dijaga view_intel di router, bukan view_news.
  const allowed = (k: RubricKey) =>
    k === "watchlist"
      ? can("view_ta")
      : k === "techstack"
        ? can("view_cve")
        : k === "ransomware"
          ? can("view_intel")
          : true;
  const cols = COLUMNS.filter((c) => (rubric ? c.key === rubric : true) && allowed(c.key));

  return (
    <section aria-labelledby="rubrics-heading">
      <h2 id="rubrics-heading" className="font-heading text-xl font-bold tracking-tight text-foreground">
        Rubrics
      </h2>
      <div className={`mt-3 grid gap-4 ${rubric ? "grid-cols-1" : "grid-cols-1 lg:grid-cols-3"}`}>
        {cols.map((c) => (
          <RubricColumn
            key={c.key}
            rkey={c.key}
            title={c.title}
            filters={filters}
            narrowed={rubric !== null}
            openArticle={openArticle}
            onSeeAll={onSeeAll}
          />
        ))}
      </div>
    </section>
  );
}
