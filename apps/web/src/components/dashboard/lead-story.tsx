"use client";

import { PanelError } from "@/components/dashboard/stat-box";
import { articleWhen, useMustRead, type Article } from "@/components/dashboard/use-dashboard-overview";
import { EntityChip } from "@/components/entities/entity-chip";
import { PriorityChip } from "@/components/newsroom/priority-chip";
import { priorityLines } from "@/components/newsroom/score-reasons";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { periodInfo, type PeriodKey } from "@/lib/dashboard/period";
import { cn } from "@/lib/utils";

const FOCUS_RING =
  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/** Artikel pertama dari query must-read bersama (satu request untuk lead dan Must read). */
export function LeadStory({
  period,
  openArticle,
}: {
  period: PeriodKey;
  openArticle: (a: Article) => void;
}) {
  const info = periodInfo(period);
  const q = useMustRead(info.days);

  // Refetch gagal tidak boleh menimpa data yang sudah ada: error hanya bila belum ada data.
  if (q.isError && !q.data) {
    return <PanelError title="Could not load the lead story" error={q.error} onRetry={() => void q.refetch()} />;
  }
  if (!q.data) return <Skeleton aria-hidden className="h-72 w-full rounded-xl" />;

  const article = q.data.articles[0];
  if (!article) {
    return (
      <StatePanel
        variant="empty"
        title={`Nothing to read ${info.suffix}`}
        description="Widen the period to see the highest-priority story."
      />
    );
  }

  const when = articleWhen(article, q.data.fetchedAt);
  const cves = article.entities.filter((e) => e.type === "vulnerability").slice(0, 2);
  const ttps = article.ttps.slice(0, 2);
  const lines = priorityLines(article);

  return (
    <article
      aria-label="Lead story"
      className={cn("surface-raised space-y-3 p-5", q.isPlaceholderData && "opacity-60")}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs font-semibold tracking-wide text-muted-foreground uppercase">
        <span>Lead story</span>
        {article.priority_score != null && (
          <>
            <span aria-hidden>·</span>
            <PriorityChip score={article.priority_score} />
          </>
        )}
        {article.story && (
          <>
            <span aria-hidden>·</span>
            <span>
              <span className="font-code">{article.story.source_count}</span>{" "}
              {article.story.source_count === 1 ? "source" : "sources"}
            </span>
          </>
        )}
        {article.llm_ttp_status === "pending" && <Chip kind="flag" value="ATT&CK PENDING" />}
      </div>
      <h2 className="text-xl leading-snug font-semibold text-foreground">
        <button
          type="button"
          onClick={() => openArticle(article)}
          className={cn("rounded-sm text-left outline-none hover:underline", FOCUS_RING)}
        >
          {article.title}
        </button>
      </h2>
      {article.summary && <p className="line-clamp-3 text-sm text-muted-foreground">{article.summary}</p>}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted-foreground">
        <span title={when.title}>
          {article.source} · {when.text}
        </span>
        {ttps.map((t) => (
          <EntityChip key={`t${t.id}`} type="attack-pattern" name={t.id} />
        ))}
        {cves.map((c) => (
          <EntityChip key={`c${c.id}`} type="vulnerability" name={c.external_id ?? c.name} />
        ))}
      </div>
      {article.priority_score != null && (
        <div className="rounded-lg bg-primary/10 p-3">
          <h3 className="text-2xs font-semibold tracking-wide text-primary-text uppercase">Why it ranks first</h3>
          <ul className="mt-1 space-y-0.5 text-xs text-foreground">
            {lines.length > 0 ? (
              lines.map((l, i) => <li key={i}>{l}</li>)
            ) : (
              <li>Ranked on source confidence alone.</li>
            )}
          </ul>
        </div>
      )}
    </article>
  );
}
