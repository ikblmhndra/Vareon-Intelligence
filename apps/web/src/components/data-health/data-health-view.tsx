"use client";

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { AttackDomainStatus } from "@/lib/api/loose-types";
import { errorStatus, isClientError } from "@/lib/exec/query";
import { fmtCompactAge, fmtTime, browserZoneName } from "@/lib/format";
import { byProblemSeverity, useScraperHealth } from "@/lib/scrapers/health";
import { noClientRetry, unwrap } from "@/lib/scrapers/queries";
import {
  TONE_STYLE,
  cveIngestTone,
  failedJobsTone,
  freshnessRows,
  llmJobsTone,
  pageStatus,
  pipelineTone,
  queueTone,
  relevanceTone,
  sigmaTone,
  worstFreshness,
  type FreshnessRow,
  type Tone,
} from "@/lib/data-health/tones";
import { usePageTitle } from "@/lib/use-page-title";
import { NeedsAttentionCard, PipelineCard } from "@/components/data-health/pipeline-card";
import { CoverageCard, FreshnessCard, StoriesCard } from "@/components/data-health/freshness-card";
import { LlmCard } from "@/components/data-health/llm-card";
import { MoreChecks } from "@/components/data-health/more-checks";
import { RelevanceCard } from "@/components/data-health/relevance-card";
import { HowToRead } from "@/components/data-health/how-to-read";
import { ToneChip } from "@/components/data-health/tone-chip";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { StatTile } from "@/components/ui/stat-tile";

function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many.replace("{n}", String(n));
}

/** Tile statis: `StatTile` tidak punya slot chip, jadi chip nada ditempel di pojok kanan atas. */
function Tile({
  label,
  value,
  sub,
  tone,
  chip,
}: {
  label: string;
  value: ReactNode;
  sub: ReactNode;
  tone: Tone;
  chip?: string;
}) {
  return (
    <StatTile
      className="h-full"
      label={label}
      value={<span className="font-code text-2xl break-words">{value}</span>}
      sub={
        <>
          <span className="mb-1 block">
            <ToneChip tone={tone}>{chip}</ToneChip>
          </span>
          {sub}
        </>
      }
      tone={TONE_STYLE[tone]}
    />
  );
}

function LoadingSkeleton() {
  return (
    <>
      <p role="status" className="sr-only">
        Loading data health
      </p>
      <div aria-hidden>
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-[88px] rounded-lg" />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-56 rounded-2xl" />
          ))}
        </div>
      </div>
    </>
  );
}

/** Halaman Data health (ROADMAP #24 PR-B): `GET /api/data-health` + kesegaran CVE (`/api/cve/freshness`)
 * dan ATT&CK (`/api/attack/status`) yang sudah ada, plus cakupan artikel dari `/api/dashboard`. Aturan nada
 * ada di `lib/data-health/tones.ts`; ambangnya ditulis di "How to read this page" (bukan `title=`). "Sekarang"
 * dibaca sekali di queryFn (`nowMs`) dan dipakai semua umur di halaman, bukan `Date.now()` saat render. */
export function DataHealthView() {
  usePageTitle("Data health");
  const [howOpen, setHowOpen] = useState(false);
  const health = useQuery({
    queryKey: ["data-health"],
    queryFn: async () => ({
      d: unwrap(await api.GET("/api/data-health"), "Could not load data health"),
      nowMs: Date.now(),
    }),
    refetchInterval: (q) => (isClientError(q.state.error) ? false : 60_000),
    retry: noClientRetry,
  });
  // Query yang sama dengan `/scrapers` (cache dibagi): status scraper `monitor_x` untuk X Intel.
  const scrapers = useScraperHealth();
  const cve = useQuery({
    queryKey: ["cve", "freshness", null],
    queryFn: async () =>
      unwrap(await api.GET("/api/cve/freshness", { params: { query: {} } }), "Could not load CVE freshness"),
    retry: noClientRetry,
  });
  const attack = useQuery({
    queryKey: ["intelligence", "attack-status"],
    queryFn: async () =>
      unwrap(await api.GET("/api/attack/status"), "Could not load ATT&CK status") as unknown as AttackDomainStatus[],
    retry: noClientRetry,
  });
  const dashboard = useQuery({
    queryKey: ["data-health", "coverage"],
    queryFn: async () => unwrap(await api.GET("/api/dashboard"), "Could not load coverage"),
    retry: noClientRetry,
  });

  const loaded = health.data;
  let header: ReactNode;
  let content: ReactNode;

  if (!loaded) {
    header = (
      <PageHeader kicker="OPERATIONS" title="Data health" description="Is the pipeline feeding the newsroom?" />
    );
    content = health.isError ? (
      errorStatus(health.error) === 403 ? (
        <StatePanel variant="no-access" title="You need the view_ops permission to see data health" />
      ) : (
        <StatePanel
          variant="error"
          title="Failed to load data health"
          action={
            <Button variant="outline" size="sm" onClick={() => void health.refetch()}>
              Retry
            </Button>
          }
        />
      )
    ) : (
      <LoadingSkeleton />
    );
  } else {
    const { d, nowMs } = loaded;
    const sched = d.scrapers.scheduler;
    const problems = byProblemSeverity(d.scrapers.problems);
    const fleetTotal = Object.values(d.scrapers.counts).reduce((a, b) => a + b, 0);

    const pipeT = pipelineTone(d.scrapers);
    const queueT = queueTone(d.queues);
    const llmT = llmJobsTone(d.llm, nowMs);
    const fresh = freshnessRows(
      {
        sources: d.sources,
        cveCheckedAt: cve.data?.last_checked_at,
        cveState: cve.data ? "ready" : cve.isError ? "failed" : "loading",
        attack: attack.data,
        attackState: attack.data ? "ready" : attack.isError ? "failed" : "loading",
      },
      nowMs,
    );
    const worst: FreshnessRow = worstFreshness(fresh);
    const relT = relevanceTone(d.relevance);
    const failT = failedJobsTone(d.enrichment);
    const cveT = cveIngestTone(d.cve_ingest);
    const sigT = sigmaTone(d.sigma);
    const status = pageStatus([pipeT, queueT, llmT, worst.tone, relT, failT, cveT, sigT]);

    const statusTitle =
      status.bad > 0
        ? plural(status.bad, "1 area needs action", "{n} areas need action")
        : status.warn > 0
          ? plural(status.warn, "1 area to watch", "{n} areas to watch")
          : status.tone === "unknown"
            ? "Status unknown"
            : "All areas OK";
    const statusSub =
      (problems.length === 0
        ? "No scraper needs attention"
        : plural(problems.length, "1 scraper needs attention", "{n} scrapers need attention")) +
      (status.bad > 0 && status.warn > 0 ? ` · ${status.warn} to watch` : "") +
      (status.unknown > 0 ? ` · ${status.unknown} unknown` : "");

    header = (
      <PageHeader
        kicker="OPERATIONS"
        title="Data health"
        description={`Generated ${fmtTime(d.generated_at)} ${browserZoneName()} · numbers cached for up to 60 s · is the pipeline feeding the newsroom?`}
        actions={
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            <a
              href="#how-to-read"
              onClick={() => setHowOpen(true)}
              className="rounded-md text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
            >
              How to read this page →
            </a>
            <div className="flex items-start gap-2.5">
              <ToneChip tone={status.tone} />
              <div>
                <p className="text-sm font-semibold text-foreground">{statusTitle}</p>
                <p className="text-xs text-muted-foreground">{statusSub}</p>
              </div>
            </div>
          </div>
        }
      />
    );

    const e = d.enrichment;
    const q = d.queues;
    const monitorX = (scrapers.data?.problems ?? []).find((p) => p.id === "monitor_x");
    const rel = d.relevance;

    const llm = d.llm;
    const pendingJobs = llm.queue.pending_classify + llm.queue.pending_ttp;

    header = (
      <>
        {header}
        {health.isError && (
          <Notice tone="warning" title={`Could not refresh · showing numbers from ${fmtTime(d.generated_at)}`} className="mb-4" />
        )}
      </>
    );

    content = (
      <>
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Tile
            label="PIPELINE"
            value={`${d.scrapers.counts.ok ?? 0} / ${fleetTotal}`}
            sub={`scrapers healthy, beat ${sched.state === "ok" ? "alive" : sched.state === "stale" ? "stale" : "heartbeat missing"}`}
            tone={pipeT}
          />
          <Tile
            label="ENRICH QUEUE"
            value={q.enrich_depth ?? "–"}
            sub={q.enrich_depth === null ? "Redis not reachable" : `of ${q.enrich_max_depth} before backpressure`}
            tone={queueT}
          />
          <Tile
            label="LLM JOBS"
            value={pendingJobs}
            sub={
              pendingJobs === 0
                ? "none pending"
                : llm.queue.oldest_pending_at
                  ? `pending, oldest ${fmtCompactAge(llm.queue.oldest_pending_at, nowMs)} ago`
                  : "pending"
            }
            tone={llmT}
          />
          <Tile
            label="FRESHNESS"
            value={worst.state === "ready" && worst.at ? fmtCompactAge(worst.at, nowMs) : "–"}
            sub={worst.tileSub}
            tone={worst.tone}
          />
          <Tile
            label="RELEVANCE"
            value={
              rel.mode === "off" ? "Off" : rel.holdout_agreement === null ? "–" : `${(rel.holdout_agreement * 100).toFixed(1)}%`
            }
            sub={
              rel.mode === "off"
                ? "relevance model is off"
                : rel.gate_state === null
                  ? "no active model yet"
                  : `holdout agreement, gate ${rel.gate_state === "gate" ? "on" : "off (shadow)"}`
            }
            tone={relT}
            chip={rel.mode === "off" ? "OFF" : undefined}
          />
          <Tile
            label="FAILED JOBS"
            value={e.failed_24h}
            sub={`created in 24 h, ${e.pending_replay} waiting`}
            tone={failT}
          />
        </div>

        <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <PipelineCard d={d} />
          <NeedsAttentionCard scrapers={d.scrapers} />
        </div>

        <LlmCard llm={llm} nowMs={nowMs} />
        <RelevanceCard rel={rel} />

        <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <FreshnessCard rows={fresh} monitorX={monitorX} nowMs={nowMs} />
          <CoverageCard dashboard={dashboard.data} failed={dashboard.isError} iocEnrichment={d.ioc_enrichment} />
          <StoriesCard day={llm.stories_24h} week={llm.stories_7d} />
        </div>

        <MoreChecks d={d} tones={{ cve: cveT, sigma: sigT, failed: failT }} nowMs={nowMs} />
      </>
    );
  }

  return (
    <div className="pb-10">
      {header}
      {content}
      <HowToRead open={howOpen} onOpenChange={setHowOpen} />
    </div>
  );
}
