"use client";

import type { components } from "@/lib/api/schema";
import type { NewsroomFilters } from "@/lib/newsroom/filters";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useArticlesQuery } from "@/components/newsroom/use-articles";

type Article = components["schemas"]["ArticleOut"];

/** Empat artikel prioritas teratas; dipakai `FrontSection` dan total di masthead
 * (react-query menyatukan dua pemanggilan dengan key yang sama menjadi satu request). */
export function useFrontQuery(filters: NewsroomFilters) {
  return useArticlesQuery(["front"], {
    page: 1,
    page_size: 4,
    sort: "priority",
    posted_on_start: filters.dateStart || undefined,
    posted_on_end: filters.dateEnd || undefined,
    country: filters.country ? [filters.country] : undefined,
    industry: filters.industry ? [filters.industry] : undefined,
    threat_actor: filters.actor ? [filters.actor] : undefined,
    search: filters.search || undefined,
    confirmed_only: filters.incidentOnly || undefined,
  });
}

function ago(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso.slice(0, 10);
  const min = Math.floor((Date.now() - t) / 60_000);
  if (min < 1) return "baru saja";
  if (min < 60) return `${min} menit lalu`;
  if (min < 48 * 60) return `${Math.floor(min / 60)} jam lalu`;
  return `${Math.floor(min / 60 / 24)} hari lalu`;
}

/** Field ini belum ada di `ArticleOut` (skema API); badge muncul begitu API mengirimnya. */
function isIncident(a: Article): boolean {
  return (a as Article & { confirmed_incident?: boolean }).confirmed_incident === true;
}

function Chips({ a }: { a: Article }) {
  const chips = [
    ...a.threat_actors.slice(0, 3).map((t) => ({ k: `a-${t}`, label: t, code: false })),
    ...a.ttps.slice(0, 3).map((t) => ({ k: `t-${t.id}`, label: t.id, code: true })),
    ...a.mentioned_countries.slice(0, 3).map((c) => ({ k: `c-${c}`, label: c, code: false })),
  ];
  if (chips.length === 0) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-1.5">
      {chips.map((c) => (
        <li key={c.k}>
          <Badge variant="outline" className={c.code ? "font-code" : undefined}>
            {c.label}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

function Kicker({ a }: { a: Article }) {
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-muted-foreground">
      {isIncident(a) && <Badge variant="destructive">Insiden</Badge>}
      {a.confidence_score != null && <span>Confidence {a.confidence_score}</span>}
      {a.news_type && <span>{a.news_type}</span>}
      <span>{ago(a.posted_on)}</span>
    </p>
  );
}

const TITLE_BUTTON =
  "text-left focus-visible:ring-3 focus-visible:ring-focus focus-visible:outline-none hover:underline";

/** Halaman depan: satu artikel utama + tiga pendamping, urut skor prioritas. */
export function FrontSection({
  filters,
  onSelect,
}: {
  filters: NewsroomFilters;
  onSelect: (a: Article) => void;
}) {
  const { data, isPending, isError, refetch } = useFrontQuery(filters);
  const articles = data?.articles ?? [];
  const [lead, ...rest] = articles;

  return (
    <section aria-label="Berita utama" className="mb-8">
      {isPending && (
        <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]" aria-busy="true">
          <div className="flex flex-col gap-3">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-3/4" />
          </div>
          <div className="flex flex-col gap-4">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        </div>
      )}
      {isError && (
        <p className="text-sm text-muted-foreground">
          Gagal memuat berita utama.{" "}
          <button type="button" onClick={() => void refetch()} className="font-medium text-primary-text hover:underline">
            Coba lagi
          </button>
        </p>
      )}
      {!isPending && !isError && !lead && (
        <p className="text-sm text-muted-foreground">Belum ada artikel untuk filter ini.</p>
      )}
      {lead && (
        <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
          <article>
            <Kicker a={lead} />
            <h2 className="mt-2 text-3xl font-bold tracking-tight text-balance">
              <button type="button" className={TITLE_BUTTON} onClick={() => onSelect(lead)}>
                {lead.title}
              </button>
            </h2>
            <Chips a={lead} />
          </article>
          <div className="flex flex-col divide-y divide-border lg:border-l lg:border-border lg:pl-6">
            {rest.map((a) => (
              <article key={a.id} className="py-3 first:pt-0 last:pb-0">
                <Kicker a={a} />
                <h3 className="mt-1 text-[15px] leading-snug font-semibold">
                  <button type="button" className={TITLE_BUTTON} onClick={() => onSelect(a)}>
                    {a.title}
                  </button>
                </h3>
              </article>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
