"use client";

import { GradeChip } from "@/components/newsroom/grade-chip";
import { PriorityChip } from "@/components/newsroom/priority-chip";
import { useArticleMatchers } from "@/components/newsroom/rubric-queries";
import { PanelError } from "@/components/dashboard/stat-box";
import { articleWhen, useMustRead, type Article } from "@/components/dashboard/use-dashboard-overview";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { periodInfo, type PeriodKey } from "@/lib/dashboard/period";
import { cn } from "@/lib/utils";

export function MustRead({ period, openArticle }: { period: PeriodKey; openArticle: (a: Article) => void }) {
  const q = useMustRead(periodInfo(period).days);
  const matches = useArticleMatchers();

  if (q.isPending) return <Skeleton aria-hidden className="h-72 w-full rounded-2xl" />;
  if (q.isError)
    return <PanelError title="Could not load the reading list" error={q.error} onRetry={() => void q.refetch()} />;

  const { articles, fetchedAt } = q.data;
  // Kosong: panel lead yang bicara (artikel 1 = lead), jadi di sini tidak ada apa-apa.
  if (articles.length === 0) return null;
  const rows = articles.slice(1, 5);

  return (
    <section className={cn(q.isPlaceholderData && "opacity-60")}>
      <h2 className="font-heading text-xl font-bold tracking-tight text-foreground">Must read</h2>
      <p className="mt-0.5 text-sm text-muted-foreground">Ranked by priority score</p>
      {rows.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">No other story in this period.</p>
      ) : (
        <ol className="mt-3 divide-y divide-border">
          {rows.map((a) => {
            const when = articleWhen(a, fetchedAt, true);
            const ttp = a.ttps[0]?.id;
            const m = matches(a);
            return (
              <li key={a.id} className="py-3">
                <div className="flex flex-wrap items-center gap-x-1.5 text-2xs font-semibold text-muted-foreground">
                  {a.priority_score != null && <PriorityChip score={a.priority_score} />}
                  {a.priority_score != null && a.news_type && <span aria-hidden>·</span>}
                  {a.news_type && <span>{a.news_type.toUpperCase()}</span>}
                </div>
                <h3 className="mt-1 text-base font-semibold leading-snug text-foreground">
                  <button
                    type="button"
                    onClick={() => openArticle(a)}
                    className="line-clamp-2 rounded text-left hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
                  >
                    {a.title}
                  </button>
                </h3>
                {a.summary && <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{a.summary}</p>}
                <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
                  <span>{a.source}</span>
                  <span aria-hidden>·</span>
                  <span title={when.title}>{when.text}</span>
                  {ttp && (
                    <>
                      <span aria-hidden>·</span>
                      <span className="font-code">{ttp}</span>
                    </>
                  )}
                  {a.confirmed_incident && <Chip kind="flag" value="Incident" />}
                  {m.watchlist && <Chip kind="flag" value="Watchlist" />}
                  {m.techstack && <Chip kind="flag" value="Tech stack" />}
                  {a.llm_ttp_status === "pending" && <Chip kind="flag" value="ATT&CK PENDING" />}
                  <GradeChip a={a} codeOnly />
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
