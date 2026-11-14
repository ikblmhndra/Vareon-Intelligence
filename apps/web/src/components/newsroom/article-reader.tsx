"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { EntityChip, EntityChipList } from "@/components/entities/entity-chip";
import { PanelError } from "@/components/dashboard/stat-box";
import { useArticleById, useStorySources } from "@/components/newsroom/all-articles-queries";
import { CredibilityOverride } from "@/components/newsroom/credibility-override";
import { PriorityChip } from "@/components/newsroom/priority-chip";
import { ReaderIocs } from "@/components/newsroom/reader-iocs";
import { ReaderMore } from "@/components/newsroom/reader-more";
import { useArticleMatchers, useWatchlistNames } from "@/components/newsroom/rubric-queries";
import { gradeLines, priorityLines } from "@/components/newsroom/score-reasons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";
import {
  actorChips,
  countryChip,
  malwareChips,
  sectorChips,
  techniqueChips,
} from "@/lib/entities/article-refs";
import { fmtDateTime } from "@/lib/format";
import { errorMessage } from "@/lib/newsletter/format";
import { addToQueue } from "@/lib/newsletter/queue";

type Article = components["schemas"]["ArticleOut"];

const TTP_SOURCE_BADGE: Record<string, string> = { explicit: "ID", keyword: "KW", llm: "LLM" };
const SECTION = "rounded-lg border border-border bg-panel p-3";
const H3 = "mb-1.5 text-2xs font-semibold uppercase tracking-wide text-muted-foreground";

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={SECTION}>
      <h3 className={H3}>{title}</h3>
      {children}
    </section>
  );
}

function ReaderSkeleton() {
  return (
    <div aria-hidden className="space-y-3">
      <Skeleton className="h-8 w-2/3" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
      {text}
    </div>
  );
}

/** Pembaca All articles (spec 6.4 blok 1-7). Artikel diambil dari daftar yang sudah dimuat; hanya
 * bila id tidak ada di sana (deep link / di luar filter) `useArticleById` ditembak. Blok IOC dan
 * "More" dipasang di bawah (Task 9). */
export function ArticleReader({
  articleId,
  listArticles,
  onStep,
}: {
  articleId: number | null;
  listArticles: Article[];
  onStep: (id: number) => void;
}) {
  const index = articleId === null ? -1 : listArticles.findIndex((a) => a.id === articleId);
  const inList = index >= 0;
  const byId = useArticleById(articleId, !inList);
  const base = inList ? listArticles[index] : byId.data;

  if (articleId === null) return <Empty text="Select an article to read it." />;
  if (!base) {
    if (byId.isError) {
      // 404 (id terhapus / tidak ada) bukan galat jaringan: katakan artikelnya tidak tersedia.
      if (byId.error instanceof Error && byId.error.cause === 404) return <Empty text="This article is not available." />;
      return <PanelError title="Could not load the article" error={byId.error} onRetry={() => void byId.refetch()} />;
    }
    return <ReaderSkeleton />;
  }
  return (
    <ReaderBody
      key={base.id}
      article={base}
      position={inList ? { i: index + 1, n: listArticles.length } : null}
      onPrev={inList && index > 0 ? () => onStep(listArticles[index - 1].id) : null}
      onNext={inList && index < listArticles.length - 1 ? () => onStep(listArticles[index + 1].id) : null}
    />
  );
}

function ReaderBody({
  article,
  position,
  onPrev,
  onNext,
}: {
  article: Article;
  position: { i: number; n: number } | null;
  onPrev: (() => void) | null;
  onNext: (() => void) | null;
}) {
  const can = useCan();
  const queryClient = useQueryClient();
  const match = useArticleMatchers();
  const rootRef = useRef<HTMLElement>(null);
  // Hasil override disimpan di sini: artikel datang dari daftar/cache dan tidak ikut refetch.
  const [updated, setUpdated] = useState<Article | null>(null);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [queueLabel, setQueueLabel] = useState("+ Newsletter");
  const [watched, setWatched] = useState(false);
  const a = updated ?? article;

  // Di bawah 1024 px pembaca ada di bawah daftar: gulirkan ke sana sekali per artikel (aturan 9).
  useEffect(() => {
    if (window.matchMedia("(max-width: 1023px)").matches) {
      rootRef.current?.scrollIntoView({ block: "start" });
    }
  }, []);

  useEffect(() => {
    if (queueLabel === "+ Newsletter") return;
    const t = setTimeout(() => setQueueLabel("+ Newsletter"), 1500);
    return () => clearTimeout(t);
  }, [queueLabel]);

  const actor = actorChips(a).find((c) => c.id != null) ?? null;
  const canManagePir = can("manage_pir");
  const watchNames = useWatchlistNames(can("view_ta"));
  const alreadyWatched =
    actor !== null &&
    (watchNames.data ?? []).some((n) => n.toLowerCase() === actor.name.toLowerCase());
  const watchMutation = useMutation({
    mutationFn: async (id: number) => {
      const { error, response } = await api.PUT("/api/entities/{entity_id}/watch", {
        params: { path: { entity_id: id } },
      });
      if (!response.ok) throw new Error(errorMessage(error));
    },
    onSuccess: () => {
      setWatched(true);
      void queryClient.invalidateQueries({ queryKey: ["ta", "watchlist-names"] });
    },
    onError: (e: Error) => toast.error(`Watch failed: ${e.message}`),
  });

  const sources = useStorySources(a.story?.id ?? null, a.id);
  const others = sources.data ?? [];
  const alsoBy =
    others.length > 0
      ? ` · also reported by ${others.slice(0, 3).join(", ")}${others.length > 3 ? ` +${others.length - 3}` : ""}`
      : "";

  const m = match(a);
  const victim = a.victim_countries ?? [];
  const origin = a.actor_countries ?? [];
  const hasRoles = victim.length > 0 || origin.length > 0;
  const countryItems = hasRoles
    ? [
        ...victim.map((c) => ({ chip: countryChip(a, c, "victim"), role: "victim", k: `v-${c}` })),
        ...origin.map((c) => ({ chip: countryChip(a, c, "actor"), role: "origin", k: `a-${c}` })),
      ]
    : (a.mentioned_countries ?? []).map((c) => ({
        chip: countryChip(a, c, "mentioned"),
        role: undefined,
        k: `m-${c}`,
      }));
  const ttpChips = techniqueChips(a, true);
  const rank = a.priority_score != null ? priorityLines(a) : [];
  // Baris "Priority N" sudah tampil di kotak "Why it ranks"; jangan diulang di Credibility.
  const why = gradeLines(a).filter((line) => !line.startsWith("Priority "));

  return (
    <article ref={rootRef} className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" nativeButton={false} render={<a href={a.url} target="_blank" rel="noopener noreferrer" />}>
          Open source ↗
        </Button>
        {canManagePir && actor && (
          <Button
            variant="outline"
            size="sm"
            disabled={alreadyWatched || watched || watchMutation.isPending}
            onClick={() => watchMutation.mutate(actor.id as number)}
          >
            {alreadyWatched || watched ? "Watching ✓" : `Watch ${actor.name}`}
          </Button>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={() => setQueueLabel(addToQueue(a) === "already" ? "Already queued" : "Queued")}
        >
          {queueLabel}
        </Button>
        {position && (
          <div className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
            <span className="font-code">
              {position.i} of {position.n}
            </span>
            <Button variant="ghost" size="icon-sm" aria-label="Previous article" disabled={!onPrev} onClick={() => onPrev?.()}>
              <ChevronLeftIcon aria-hidden />
            </Button>
            <Button variant="ghost" size="icon-sm" aria-label="Next article" disabled={!onNext} onClick={() => onNext?.()}>
              <ChevronRightIcon aria-hidden />
            </Button>
          </div>
        )}
      </div>

      <header className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-1.5">
          {a.news_type && <span className="text-xs text-muted-foreground">{a.news_type}</span>}
          {a.confirmed_incident && <Chip kind="flag" value="Incident" />}
          {m.watchlist && <Chip kind="flag" value="Watchlist" />}
          {m.techstack && <Chip kind="flag" value="Tech stack" />}
          {a.priority_score != null && <PriorityChip score={a.priority_score} />}
        </div>
        <h2 className="font-heading text-base leading-snug font-semibold text-foreground">{a.title}</h2>
        <p className="text-xs text-muted-foreground">
          {a.source}
          {a.first_seen_at ? ` · ${fmtDateTime(a.first_seen_at)}` : ""}
          {alsoBy}
        </p>
      </header>

      {a.admiralty_code && (
        <section className={SECTION}>
          <h3 className={H3}>Credibility</h3>
          <div className="flex items-start gap-3">
            <span className="font-code text-3xl leading-none font-semibold text-foreground">{a.admiralty_code}</span>
            <div className="min-w-0 space-y-1 text-xs text-foreground">
              {/* Nilai kredibilitas sudah ada di baris gradeLines; kalimat ini hanya untuk kasus tanpa nilai. */}
              {a.credibility == null && <p>Information credibility unrated.</p>}
              <p className="text-muted-foreground">Why this grade:</p>
              <ul className="list-disc space-y-0.5 pl-4">
                {why.map((line) => (
                  <li key={line}>{line}</li>
                ))}
                {/* PIR / aset sendiri sudah difilter API ke client penonton (P7f). */}
                {a.score_reasons.pir.map((p) => (
                  <li key={`pir-${p.id}`}>{`PIR: ${p.title} (${p.priority})`}</li>
                ))}
                {a.score_reasons.own_asset.length > 0 && (
                  <li>{`Own asset: ${a.score_reasons.own_asset.join(", ")}`}</li>
                )}
              </ul>
              {can("manage_intel") && (
                <Button variant="ghost" size="sm" aria-expanded={overrideOpen} onClick={() => setOverrideOpen((o) => !o)}>
                  Override
                </Button>
              )}
            </div>
          </div>
          {can("manage_intel") && overrideOpen && (
            <CredibilityOverride key={a.id} article={a} onSaved={setUpdated} />
          )}
        </section>
      )}

      {rank.length > 0 && (
        <section className={SECTION}>
          <h3 className={H3}>Why it ranks</h3>
          <ul className="list-disc space-y-0.5 pl-4 text-xs text-foreground">
            {rank.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>
      )}

      {a.summary && <p className="text-sm leading-relaxed text-foreground">{a.summary}</p>}

      <div className="grid gap-3 sm:grid-cols-2">
        {actorChips(a).length > 0 && (
          <Card title="Threat actors">
            <EntityChipList items={actorChips(a)} max={12} />
          </Card>
        )}
        {malwareChips(a).length > 0 && (
          <Card title="Malware / tools">
            <EntityChipList items={malwareChips(a)} max={12} />
          </Card>
        )}
        {countryItems.length > 0 && (
          <Card title="Countries">
            <div className="flex flex-wrap gap-1.5">
              {countryItems.map((c) => (
                <span key={c.k} className="inline-flex items-center gap-1">
                  <EntityChip {...c.chip} />
                  {c.role && <span className="text-2xs text-muted-foreground">{c.role}</span>}
                </span>
              ))}
            </div>
          </Card>
        )}
        {sectorChips(a).length > 0 && (
          <Card title="Impacted industries">
            <div className="flex flex-wrap items-center gap-1.5">
              <EntityChipList items={sectorChips(a)} max={12} />
              {a.industry_source === "keyword" && <span className="text-2xs text-muted-foreground">KW</span>}
            </div>
          </Card>
        )}
      </div>

      {(a.ttps.length > 0 || a.llm_ttp_status === "pending") && (
        <Card title="MITRE ATT&CK TTPs">
          {a.ttps.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {a.ttps.map((t, i) => {
                const label = TTP_SOURCE_BADGE[t.source] ?? t.source;
                return (
                  <span key={t.id} className="inline-flex items-center gap-1">
                    <EntityChip {...ttpChips[i]} />
                    {t.evidence ? (
                      <Tooltip>
                        <TooltipTrigger render={<span tabIndex={0} />}>
                          <Badge variant="outline" className="text-2xs">{label}</Badge>
                        </TooltipTrigger>
                        <TooltipContent>{t.evidence}</TooltipContent>
                      </Tooltip>
                    ) : (
                      <Badge variant="outline" className="text-2xs">{label}</Badge>
                    )}
                  </span>
                );
              })}
            </div>
          )}
          {a.llm_ttp_status === "pending" && (
            <p className="mt-2 text-xs text-muted-foreground">ATT&amp;CK tagging pending</p>
          )}
        </Card>
      )}

      <ReaderIocs article={a} />
      <ReaderMore article={a} />
    </article>
  );
}
