"use client";

import { PanelError } from "@/components/dashboard/stat-box";
import type { Source as SheetSource } from "@/components/newsroom/article-list-sheet";
import { useTopics } from "@/components/newsroom/newsroom-queries";
import { BarSeries } from "@/components/ui/bar-series";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import type { components } from "@/lib/api/schema";
import type { NewsroomFilters } from "@/lib/newsroom/filters";
import { cn } from "@/lib/utils";

type Topic = components["schemas"]["TopicOut"];

const GRID = "mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6";

/** Topik aktif: tren aktor/teknik (D14), bukan klaster cerita. Sheet dibuka lewat tombol nama. */
export function TopicsSection({
  filters,
  words,
  onOpen,
}: {
  filters: NewsroomFilters;
  words: string;
  onOpen: (source: SheetSource, title: string) => void;
}) {
  const q = useTopics(filters);

  function open(t: Topic) {
    if (t.kind === "ttp") onOpen({ ttp: t.ttp_id ?? t.name }, [t.ttp_id, t.name].filter(Boolean).join(" "));
    else onOpen({ actor: t.name }, t.name);
  }

  return (
    <section className={cn(q.isPlaceholderData && "opacity-60")}>
      <h2 className="font-heading text-xl font-bold tracking-tight text-foreground">Active topics</h2>
      <p className="mt-0.5 text-sm text-muted-foreground">Rising actors and techniques, {words}</p>
      {q.isPending ? (
        <div aria-hidden className={GRID}>
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-40 w-full rounded-xl" />
          ))}
        </div>
      ) : q.isError && !q.data ? (
        <PanelError
          title="Could not load active topics"
          error={q.error}
          onRetry={() => void q.refetch()}
          className="mt-3"
        />
      ) : q.data && q.data.items.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">Nothing is rising in this period.</p>
      ) : (
        <ul className={GRID}>
          {q.data?.items.map((t) => {
            const days = q.data.window_days;
            const today = t.daily[t.daily.length - 1] ?? 0;
            return (
              <li key={`${t.kind}-${t.ttp_id ?? t.name}`} className="min-w-0 rounded-xl border border-border bg-card p-3">
                <Chip kind="flag" value={t.kind === "ttp" ? "Technique" : "Actor"} />
                <h3 className="mt-2 text-sm font-semibold leading-snug text-foreground">
                  <button
                    type="button"
                    onClick={() => open(t)}
                    className="line-clamp-2 rounded text-left hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
                  >
                    {t.kind === "ttp" && t.ttp_id ? (
                      <>
                        <span className="font-code">{t.ttp_id}</span> {t.name}
                      </>
                    ) : (
                      t.name
                    )}
                  </button>
                </h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  <span className="font-code text-sm font-semibold text-foreground">{t.count.toLocaleString("en-US")}</span>
                  {today > 0 && <span> · +{today.toLocaleString("en-US")} today</span>}
                </p>
                <div className="mt-2">
                  <div aria-hidden>
                    <BarSeries
                      labels={t.daily.map((_, i) => String(i + 1))}
                      values={t.daily}
                      highlightLast={1}
                      height={48}
                      aria-label={t.name}
                    />
                  </div>
                  <span className="sr-only">
                    {t.count.toLocaleString("en-US")} mentions in {days.toLocaleString("en-US")} {days === 1 ? "day" : "days"}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
