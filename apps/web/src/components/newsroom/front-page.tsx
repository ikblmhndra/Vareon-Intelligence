"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { XIcon } from "lucide-react";

import { PanelError } from "@/components/dashboard/stat-box";
import { articleWhen } from "@/components/dashboard/use-dashboard-overview";
import { EntityChip } from "@/components/entities/entity-chip";
import { GradeChip } from "@/components/newsroom/grade-chip";
import { useFrontArticles, useNewestMatch, type Narrowing } from "@/components/newsroom/newsroom-queries";
import { PriorityChip } from "@/components/newsroom/priority-chip";
import { useArticleMatchers } from "@/components/newsroom/rubric-queries";
import { priorityLines } from "@/components/newsroom/score-reasons";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import type { components } from "@/lib/api/schema";
import { countryName } from "@/lib/dashboard/countries";
import { actorChips } from "@/lib/entities/article-refs";
import { fmtAgo, fmtShortDate, fmtTime, parseLocalDate } from "@/lib/format";
import type { NewsroomFilters } from "@/lib/newsroom/filters";
import { newsroomPeriodInfo, type NewsroomPeriod, type NewsroomUi } from "@/lib/newsroom/period";
import { cn } from "@/lib/utils";

type Article = components["schemas"]["ArticleOut"];

const FOCUS_RING =
  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

// Judul rubrik untuk chip filter dan kalimat state kosong (salinan lokal: peta di newsroom-view tidak diekspor).
const RUBRIC_TITLES = {
  apac: "APAC",
  global: "Global",
  local: "Local",
  ransomware: "Ransomware",
  watchlist: "Watchlist",
  techstack: "Tech stack",
} as const;

// Tombol "perlebar" state kosong: periode berikutnya; All tidak punya lanjutan.
const WIDEN: Partial<Record<NewsroomPeriod, { next: NewsroomPeriod; label: string }>> = {
  "1": { next: "7", label: "Show last 7 days" },
  "7": { next: "30", label: "Show last 30 days" },
  "30": { next: "all", label: "Show all time" },
};

type Matchers = ReturnType<typeof useArticleMatchers>;

function Flags({ a, match }: { a: Article; match: Matchers }) {
  const m = match(a);
  if (!a.confirmed_incident && !m.watchlist && !m.techstack && a.llm_ttp_status !== "pending") return null;
  return (
    <>
      {a.confirmed_incident && <Chip kind="flag" value="Incident" />}
      {m.watchlist && <Chip kind="flag" value="Watchlist" />}
      {m.techstack && <Chip kind="flag" value="Tech stack" />}
      {a.llm_ttp_status === "pending" && <Chip kind="flag" value="ATT&CK PENDING" />}
    </>
  );
}

function Lead({
  a,
  fetchedAt,
  match,
  openArticle,
  onOpenStory,
}: {
  a: Article;
  fetchedAt: number;
  match: Matchers;
  openArticle: (a: Article) => void;
  onOpenStory: (storyId: number, title: string) => void;
}) {
  const when = articleWhen(a, fetchedAt);
  const lines = priorityLines(a);
  const ttps = a.ttps.slice(0, 2);
  const cve = a.entities.find((e) => e.type === "vulnerability");
  const actor = actorChips(a)[0];
  const story = a.story && a.story.source_count > 1 ? a.story : null;
  return (
    <article aria-label="Top story" className="surface-raised space-y-3 p-5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs font-semibold tracking-wide text-muted-foreground uppercase">
        <span>Top story</span>
        {a.news_type && (
          <>
            <span aria-hidden>·</span>
            <span>{a.news_type}</span>
          </>
        )}
        {a.priority_score != null && (
          <>
            <span aria-hidden>·</span>
            <PriorityChip score={a.priority_score} />
          </>
        )}
        <GradeChip a={a} codeOnly />
      </div>
      <h2 className="text-xl leading-snug font-semibold text-foreground">
        <button
          type="button"
          onClick={() => openArticle(a)}
          className={cn("rounded-sm text-left outline-none hover:underline", FOCUS_RING)}
        >
          {a.title}
        </button>
      </h2>
      {a.summary && <p className="line-clamp-3 text-sm text-muted-foreground">{a.summary}</p>}
      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-2 text-xs text-muted-foreground">
        <span>{a.source}</span>
        {story && (
          <button
            type="button"
            onClick={() => onOpenStory(story.id, a.title)}
            className={cn("rounded-sm font-medium text-primary-text outline-none hover:underline", FOCUS_RING)}
          >
            +<span className="font-code">{story.source_count - 1}</span> sources
          </button>
        )}
        <span aria-hidden>·</span>
        <span title={when.title}>{when.text}</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {ttps.map((t) => (
          <EntityChip key={`t${t.id}`} type="attack-pattern" name={t.id} />
        ))}
        {cve && <EntityChip type="vulnerability" name={cve.external_id ?? cve.name} />}
        {actor && <EntityChip {...actor} />}
        <Flags a={a} match={match} />
      </div>
      {a.priority_score != null && lines.length > 0 && (
        <p className="text-xs text-foreground">
          <span className="mr-2 text-2xs font-semibold tracking-wide text-primary-text uppercase">
            Why it ranks first
          </span>
          {lines.join(" · ")}
        </p>
      )}
    </article>
  );
}

function Secondary({
  a,
  fetchedAt,
  match,
  openArticle,
}: {
  a: Article;
  fetchedAt: number;
  match: Matchers;
  openArticle: (a: Article) => void;
}) {
  const when = articleWhen(a, fetchedAt, true);
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-x-1.5 text-2xs font-semibold text-muted-foreground uppercase">
        {a.news_type && <span>{a.news_type}</span>}
        <GradeChip a={a} codeOnly />
      </div>
      <h3 className="mt-1 text-base leading-snug font-semibold text-foreground">
        <button
          type="button"
          onClick={() => openArticle(a)}
          className={cn("line-clamp-2 rounded-sm text-left outline-none hover:underline", FOCUS_RING)}
        >
          {a.title}
        </button>
      </h3>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
        <span>{a.source}</span>
        <span aria-hidden>·</span>
        <span title={when.title}>{when.text}</span>
        <Flags a={a} match={match} />
      </div>
    </li>
  );
}

/** Chip filter aktif di state kosong: tombolnya sendiri menghapus filter itu (bukan chip di dalam tombol). */
function RemovableChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <button
      type="button"
      aria-label={`Remove filter ${label}`}
      onClick={onRemove}
      className={cn(
        "inline-flex items-center gap-1 rounded-full bg-panel px-2.5 py-1 text-xs text-foreground outline-none hover:bg-muted",
        FOCUS_RING,
      )}
    >
      {label}
      <XIcon aria-hidden className="size-3" />
    </button>
  );
}

function EmptyFront({
  ui,
  narrowing,
  onChange,
}: {
  ui: NewsroomUi;
  narrowing: Narrowing;
  onChange: (p: Partial<NewsroomUi>) => void;
}) {
  // Dipanggil hanya saat front query selesai dengan nol artikel, jadi query "terbaru tanpa periode" boleh jalan.
  const newest = useNewestMatch(narrowing, true);
  const info = newsroomPeriodInfo(ui.period);
  const from = ui.from ? fmtShortDate(parseLocalDate(ui.from)) : null;
  const parts = [
    ui.country && `for ${countryName(ui.country)}`,
    ui.search && `matching “${ui.search}”`,
    ui.rubric && `in ${RUBRIC_TITLES[ui.rubric]}`,
  ].filter(Boolean);
  const title = `No articles ${from ? `since ${from}` : info.suffix}${parts.length ? ` ${parts.join(", ")}` : ""}`;

  let description: string | undefined;
  if (newest.isSuccess) {
    const first = newest.data.article?.first_seen_at;
    description =
      newest.data.article && first
        ? `The newest match is from ${fmtAgo(first, newest.dataUpdatedAt)}. Widen the period or remove a filter.`
        : "Nothing matches these filters at any time.";
  } else if (newest.isError) {
    description = "Widen the period or remove a filter.";
  }

  const widen = ui.from ? undefined : WIDEN[ui.period];
  return (
    <StatePanel
      variant="empty"
      title={title}
      description={description}
      action={
        <div className="flex flex-col items-center gap-3">
          <div className="flex flex-wrap items-center justify-center gap-2">
            {ui.search && <RemovableChip label={`“${ui.search}”`} onRemove={() => onChange({ search: "" })} />}
            {ui.country && (
              <RemovableChip label={countryName(ui.country)} onRemove={() => onChange({ country: null })} />
            )}
            {ui.rubric && (
              <RemovableChip label={RUBRIC_TITLES[ui.rubric]} onRemove={() => onChange({ rubric: null })} />
            )}
            {ui.incidentOnly && (
              <RemovableChip label="Incidents only" onRemove={() => onChange({ incidentOnly: false })} />
            )}
            {from && <RemovableChip label={`From ${from}`} onRemove={() => onChange({ from: null })} />}
          </div>
          {widen && (
            <Button variant="outline" size="sm" onClick={() => onChange({ period: widen.next })}>
              {widen.label}
            </Button>
          )}
        </div>
      }
    />
  );
}

/** Halaman depan: satu artikel utama + tiga pendamping, urut prioritas, dipersempit oleh rubrik terpilih. */
export function FrontPage({
  ui,
  narrowing,
  onChange,
  openArticle,
  onOpenStory,
}: {
  ui: NewsroomUi;
  filters: NewsroomFilters;
  narrowing: Narrowing;
  onChange: (p: Partial<NewsroomUi>) => void;
  openArticle: (a: Article) => void;
  onOpenStory: (storyId: number, title: string) => void;
}) {
  const queryClient = useQueryClient();
  const q = useFrontArticles(narrowing);
  const match = useArticleMatchers();

  // Ransomware = daftar korban, bukan artikel: blok ini tidak dirender.
  if (narrowing === "victims") return null;
  if (narrowing === "pending") return <Skeleton aria-hidden className="h-70 w-full rounded-xl" />;
  // Tanpa nama, filter kosong berarti "semua"; jangan tampilkan feed penuh (Review Focus 2).
  if (narrowing === "no-names") {
    return (
      <p className="text-sm text-muted-foreground">
        {ui.rubric === "techstack" ? (
          <>
            No tech stack yet.{" "}
            <Link href="/cve" className={cn("rounded-sm font-medium text-primary-text hover:underline", FOCUS_RING)}>
              Set up tech stack
            </Link>
          </>
        ) : (
          "No watched actors yet."
        )}
      </p>
    );
  }

  if (q.isError && !q.data) {
    return <PanelError title="Could not load the front page" error={q.error} onRetry={() => void q.refetch()} />;
  }
  if (!q.data) {
    return (
      <div aria-hidden className="grid gap-6 lg:grid-cols-[minmax(0,820fr)_minmax(0,468fr)]">
        <Skeleton className="h-70 w-full rounded-xl" />
        <div className="flex flex-col gap-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      </div>
    );
  }

  const [lead, ...rest] = q.data.articles;
  const message = q.error instanceof Error && q.error.message ? q.error.message : "The request failed.";
  return (
    <div className="space-y-4">
      {q.isError && (
        <Notice
          tone="warning"
          title="Could not refresh the newsroom"
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void queryClient.refetchQueries({ queryKey: ["newsroom"] });
                void queryClient.refetchQueries({ queryKey: ["ransomware", "victims"] });
              }}
            >
              Try again
            </Button>
          }
        >
          {message} Showing the copy from {fmtTime(new Date(q.dataUpdatedAt))}; your filters are kept.
        </Notice>
      )}
      {!lead ? (
        <EmptyFront ui={ui} narrowing={narrowing} onChange={onChange} />
      ) : (
        <div
          className={cn(
            "grid gap-6 lg:grid-cols-[minmax(0,820fr)_minmax(0,468fr)]",
            q.isPlaceholderData && "opacity-60",
          )}
        >
          <Lead a={lead} fetchedAt={q.dataUpdatedAt} match={match} openArticle={openArticle} onOpenStory={onOpenStory} />
          {rest.length > 0 && (
            <ol aria-label="Also on the front page" className="divide-y divide-border">
              {rest.slice(0, 3).map((a) => (
                <Secondary key={a.id} a={a} fetchedAt={q.dataUpdatedAt} match={match} openArticle={openArticle} />
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}
