"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { AttackDomainStatus } from "@/lib/api/loose-types";
import { formatWib, relativeTime } from "@/lib/cve/freshness";
import { byProblemSeverity, useScraperHealth } from "@/lib/scrapers/health";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/scrapers/status-badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

type Tone = "ok" | "warn" | "bad" | "unknown";

const HOUR_MS = 3_600_000;

const TONE_STYLE: Record<Tone, string> = {
  ok: "bg-success/12 text-success-text",
  warn: "bg-warning/15 text-warning-text",
  bad: "bg-destructive/15 text-destructive-text",
  unknown: "bg-muted-foreground/12 text-muted-foreground",
};

const TONE_LABEL: Record<Tone, string> = { ok: "OK", warn: "Check", bad: "Problem", unknown: "Unknown" };

/** Umur cap waktu dalam jam; `null` kalau kosong/tidak valid (`relativeTime` menulis "NaNd ago"). */
function ageHours(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : (Date.now() - ms) / HOUR_MS;
}

/** "3h 12m ago · 23 Oct 2026, 10:04 WIB", atau "never" -- dengan penjaga nilai kosong/tidak valid. */
function when(iso: string | null | undefined): string {
  if (!iso || Number.isNaN(Date.parse(iso))) return "never";
  return `${relativeTime(iso)} · ${formatWib(iso)}`;
}

function byAge(iso: string | null | undefined, warnH: number, badH: number): Tone {
  const h = ageHours(iso);
  if (h === null) return "unknown";
  return h > badH ? "bad" : h > warnH ? "warn" : "ok";
}

function pct(part: number, whole: number): string {
  return whole > 0 ? `${Math.round((part / whole) * 100)}%` : "—";
}

const CELL = "px-2 py-1.5 text-xs sm:text-sm";
const HEAD = "h-8 px-2 text-xs";
const NUM = cn(CELL, "text-right tabular-nums whitespace-nowrap");

/** "12 / 340"; `—` untuk nilai kosong (token/latensi nullable, atau tugas tanpa panggilan di jendela itu). */
function pair(a: number | null | undefined, b: number | null | undefined, unit = ""): string {
  const f = (n: number | null | undefined) => (n === null || n === undefined ? "—" : `${n.toLocaleString()}${unit}`);
  return `${f(a)} / ${f(b)}`;
}

/** Halaman Data health (ROADMAP #24 PR-B): `GET /api/data-health` + kesegaran CVE (`/api/cve/freshness`)
 * dan ATT&CK (`/api/attack/status`) yang sudah ada, plus cakupan artikel dari `/api/dashboard`. Ambang
 * warna ditulis di "How to read this page" (bukan `title=`), dan setiap nada punya label teks. */
export function DataHealthView() {
  const health = useQuery({
    queryKey: ["data-health"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/data-health");
      if (error) throw error;
      return data;
    },
    refetchInterval: 60_000,
  });
  // Query yang sama dengan `/scrapers` (cache dibagi): status scraper `monitor_x` untuk X Intel.
  const scrapers = useScraperHealth();
  const cve = useQuery({
    queryKey: ["cve", "freshness", null],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/cve/freshness", { params: { query: {} } });
      if (error) throw error;
      return data;
    },
  });
  const attack = useQuery({
    queryKey: ["intelligence", "attack-status"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/attack/status");
      if (error) throw error;
      return data as unknown as AttackDomainStatus[];
    },
  });
  const dashboard = useQuery({
    queryKey: ["data-health", "coverage"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/dashboard");
      if (error) throw error;
      return data;
    },
  });

  if (health.isPending) {
    return (
      <div aria-hidden className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-56 rounded-2xl" />
        ))}
      </div>
    );
  }
  if (health.isError || !health.data) {
    return <p className="text-sm text-destructive-text">Failed to load data health.</p>;
  }

  const d = health.data;
  const sched = d.scrapers.scheduler;
  const problems = byProblemSeverity(d.scrapers.problems);
  const fleetTotal = Object.values(d.scrapers.counts).reduce((a, b) => a + b, 0);
  const pipelineTone: Tone = sched.state !== "ok" ? "bad" : problems.length ? "warn" : "ok";

  const e = d.enrichment;
  const failRate = e.processed_7d > 0 ? e.failed_7d / e.processed_7d : 0;
  const enrichTone: Tone = failRate >= 0.1 || e.failed_24h >= 5 ? "bad" : e.pending_replay > 0 ? "warn" : "ok";

  const q = d.queues;
  const queueTone: Tone =
    q.enrich_depth === null
      ? "unknown"
      : q.enrich_depth >= q.enrich_max_depth
        ? "bad"
        : q.enrich_depth >= q.enrich_max_depth / 2
          ? "warn"
          : "ok";

  const monitorX = (scrapers.data?.problems ?? []).find((p) => p.id === "monitor_x");
  const attackDomains = attack.data ?? [];
  const attackTone: Tone = attack.isError
    ? "unknown"
    : attackDomains.some((x) => x.status === "error")
      ? "bad"
      : attackDomains.some((x) => (ageHours(x.last_sync) ?? Infinity) > 30 * 24)
        ? "warn"
        : attackDomains.length
          ? "ok"
          : "unknown";
  const newestAttackSync = attackDomains
    .map((x) => x.last_sync)
    .filter((x): x is string => !!x && !Number.isNaN(Date.parse(x)))
    .sort()
    .at(-1);

  const cov = dashboard.data;

  const llm = d.llm;
  const llmTone: Tone = llm.status === "ok" ? "ok" : llm.status === "failing" ? "bad" : "unknown";
  const le = llm.last_error;
  const llmStatusValue =
    llm.status === "failing"
      ? le
        ? `${[le.http_status, le.error_type].filter((x) => x !== null).join(" ") || "error"} · ${le.task} · ${when(le.at)}`
        : "latest call returned no choices"
      : llm.status === "ok"
        ? `last successful call ${when(llm.last_ok_at)}`
        : "no calls recorded yet";
  const usage7d = new Map(llm.usage_7d.map((u) => [u.task, u]));
  const llmTasks = [...new Set([...llm.usage_24h.map((u) => u.task), ...usage7d.keys()])].sort();
  const usage24h = new Map(llm.usage_24h.map((u) => [u.task, u]));

  return (
    <div className="pb-10">
      <p className="mb-6 text-sm text-muted-foreground">
        Updated {when(d.generated_at)}. Numbers are cached for up to 60 seconds and refresh every minute.
      </p>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Section title="Pipeline" tone={pipelineTone}>
          <Row label="Scheduler (beat)" value={sched.state === "ok" ? `alive, last tick ${when(sched.last_tick_at)}` : `${sched.state.toUpperCase()}, last tick ${when(sched.last_tick_at)}`} tone={sched.state === "ok" ? "ok" : "bad"} />
          <Row label="Scrapers" value={`${fleetTotal} total · ${d.scrapers.counts.ok ?? 0} ok · ${d.scrapers.counts.disabled ?? 0} disabled · ${problems.length} need attention`} />
          {problems.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {problems.slice(0, 8).map((p) => (
                <li key={p.id} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-sm">
                  <StatusBadge status={p.status} />
                  <span className="font-code text-xs text-foreground">{p.id}</span>
                  {p.reason && <span className="text-xs text-muted-foreground">{p.reason}</span>}
                </li>
              ))}
              {problems.length > 8 && (
                <li className="text-xs text-muted-foreground">and {problems.length - 8} more</li>
              )}
            </ul>
          )}
          <MoreLink href="/scrapers">Open Scrapers</MoreLink>
        </Section>

        <Section title="Enrichment" tone={enrichTone}>
          <Row label="Failed, last 24 hours" value={e.failed_24h.toLocaleString()} />
          <Row
            label="Failed, last 7 days"
            value={`${e.failed_7d.toLocaleString()} of ${e.processed_7d.toLocaleString()} processed (${pct(e.failed_7d, e.processed_7d)})`}
          />
          <Row label="Waiting for a replay" value={e.pending_replay.toLocaleString()} tone={e.pending_replay ? "warn" : "ok"} />
          <Row label="Last failure" value={when(e.last_failure_at)} />
          <Row
            label="Enrich queue"
            value={q.enrich_depth === null ? "unknown (Redis not reachable)" : `${q.enrich_depth.toLocaleString()} waiting · backpressure at ${q.enrich_max_depth.toLocaleString()}`}
            tone={queueTone}
          />
          <MoreLink href="/newsroom">Replay from Newsroom › Filtered Articles › Failed enrichment</MoreLink>
        </Section>

        <Section title="Source freshness">
          <Row label="Newest article" value={when(d.sources.articles_newest_at)} tone={byAge(d.sources.articles_newest_at, 6, 24)} />
          <Row
            label="Newest tweet (X Intel)"
            value={`${when(d.sources.tweets_newest_at)}${monitorX ? ` · monitor_x ${monitorX.status.replace("_", " ")}${monitorX.reason ? `: ${monitorX.reason}` : ""}` : ""}`}
            tone={byAge(d.sources.tweets_newest_at, 24, 72)}
          />
          <Row label="Newest IOC extracted" value={when(d.sources.iocs_newest_at)} tone={byAge(d.sources.iocs_newest_at, 24, 72)} />
          <Row
            label="CVE check"
            value={cve.isError ? "unknown (failed to load)" : cve.data ? `last successful check ${when(cve.data.last_checked_at)}` : "loading…"}
            tone={cve.isError ? "unknown" : cve.data ? byAge(cve.data.last_checked_at, 6, 24) : "unknown"}
          />
          <Row
            label="ATT&CK"
            value={attack.isError ? "unknown (failed to load)" : attack.data ? `last sync ${when(newestAttackSync)}` : "loading…"}
            tone={attackTone}
          />
        </Section>

        <Section title="Coverage">
          {cov ? (
            <>
              <Row label="Articles with a country" value={`${cov.coverage.with_country.toLocaleString()} of ${cov.total_articles.toLocaleString()} (${pct(cov.coverage.with_country, cov.total_articles)})`} />
              <Row label="Articles with a threat actor" value={`${cov.coverage.with_actor.toLocaleString()} (${pct(cov.coverage.with_actor, cov.total_articles)})`} />
              <Row label="Articles with an ATT&CK technique" value={`${cov.coverage.with_ttp.toLocaleString()} (${pct(cov.coverage.with_ttp, cov.total_articles)})`} />
            </>
          ) : (
            <Row label="Articles" value={dashboard.isError ? "unknown (failed to load)" : "loading…"} />
          )}
          <h3 className="mt-4 mb-1 text-sm font-semibold text-foreground">IOC reputation checks</h3>
          {d.ioc_enrichment.length === 0 ? (
            <p className="text-sm text-muted-foreground">No IOCs yet.</p>
          ) : (
            d.ioc_enrichment.map((c) => (
              <Row
                key={c.type}
                label={c.type}
                code
                value={`${c.enriched.toLocaleString()} of ${c.total.toLocaleString()} checked (${pct(c.enriched, c.total)})`}
              />
            ))
          )}
        </Section>

        <div className="space-y-4 lg:col-span-2">
          <Section title="LLM" tone={llmTone}>
            <Row label="Model status" value={llmStatusValue} tone={llmTone} />
            <Row
              label="Parked articles"
              value={`${llm.parked.total.toLocaleString()} parked · ${llm.parked.auto_eligible.toLocaleString()} eligible for auto-replay · ${llm.parked.auto_replays_24h.toLocaleString()} auto-replays in 24 h`}
              tone={llm.parked.total ? "warn" : "ok"}
            />
            <Row label="Stories, last 24 hours" value={storySummary(llm.stories_24h)} />
            <Row label="Stories, last 7 days" value={storySummary(llm.stories_7d)} />
            <MoreLink href="/newsroom">Replay from Newsroom › Filtered Articles › Failed enrichment</MoreLink>
          </Section>
          <Table framed>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className={HEAD}>Task</TableHead>
                <TableHead className={cn(HEAD, "text-right")}>Calls 24 h / 7 d</TableHead>
                <TableHead className={cn(HEAD, "text-right")}>Errors 24 h / 7 d</TableHead>
                <TableHead className={cn(HEAD, "text-right")}>Prompt tokens 24 h / 7 d</TableHead>
                <TableHead className={cn(HEAD, "text-right")}>Completion tokens 24 h / 7 d</TableHead>
                <TableHead className={cn(HEAD, "text-right")}>Median latency 24 h / 7 d</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {llmTasks.length === 0 ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={6} className="px-2 py-3 text-sm text-muted-foreground">
                    No LLM calls recorded in the last 7 days.
                  </TableCell>
                </TableRow>
              ) : (
                llmTasks.map((task) => {
                  const a = usage24h.get(task);
                  const b = usage7d.get(task);
                  return (
                    <TableRow key={task}>
                      <TableCell className={cn(CELL, "font-code")}>{task}</TableCell>
                      <TableCell className={NUM}>{pair(a?.calls, b?.calls)}</TableCell>
                      <TableCell className={NUM}>{pair(a?.errors, b?.errors)}</TableCell>
                      <TableCell className={NUM}>{pair(a?.prompt_tokens, b?.prompt_tokens)}</TableCell>
                      <TableCell className={NUM}>{pair(a?.completion_tokens, b?.completion_tokens)}</TableCell>
                      <TableCell className={NUM}>{pair(a?.median_latency_ms, b?.median_latency_ms, " ms")}</TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      <HowToRead />
    </div>
  );
}

function storySummary(s: { new_stories: number; followups: number; inherited: number; llm_calls_avoided: number }) {
  return `${s.new_stories.toLocaleString()} new · ${s.followups.toLocaleString()} follow-ups · ${s.inherited.toLocaleString()} inherited · ${s.llm_calls_avoided.toLocaleString()} LLM calls avoided`;
}

function Section({ title, tone, children }: { title: string; tone?: Tone; children: ReactNode }) {
  return (
    <section className="surface-raised rounded-2xl p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="font-heading text-xl font-bold tracking-tight text-foreground">{title}</h2>
        {tone && <TonePill tone={tone} />}
      </div>
      <dl className="divide-y divide-border/70">{children}</dl>
    </section>
  );
}

function Row({ label, value, tone, code }: { label: string; value: string; tone?: Tone; code?: boolean }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2">
      <dt className={cn("text-sm text-muted-foreground", code && "font-code")}>{label}</dt>
      <dd className="flex min-w-0 items-baseline gap-2 text-right text-sm text-foreground tabular-nums">
        <span className="min-w-0 break-words">{value}</span>
        {tone && <TonePill tone={tone} />}
      </dd>
    </div>
  );
}

function TonePill({ tone }: { tone: Tone }) {
  return (
    <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold", TONE_STYLE[tone])}>
      {TONE_LABEL[tone]}
    </span>
  );
}

function MoreLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="mt-3 inline-block text-sm font-medium text-primary-text rounded-sm underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-focus"
    >
      {children}
    </Link>
  );
}

function HowToRead() {
  return (
    <details className="mt-6 rounded-2xl surface-raised p-4 text-sm">
      <summary className="cursor-pointer font-medium">How to read this page</summary>
      <ul className="mt-3 list-disc space-y-1.5 pl-5 text-muted-foreground">
        <li>
          <strong className="text-foreground">Pipeline</strong>: Problem when the scheduler (beat) heartbeat is stale or missing;
          Check when any scraper needs attention (the statuses are explained on the Scrapers page).
        </li>
        <li>
          <strong className="text-foreground">Enrichment</strong>: Problem when 10% or more of the articles processed in 7 days
          failed, or 5 or more failed in 24 hours; Check when failed articles are still waiting for a replay. A failed article is
          stored but not enriched until it is replayed.
        </li>
        <li>
          <strong className="text-foreground">Enrich queue</strong>: Check at half of the backpressure limit, Problem at the
          limit (scrapers then stop handing over new articles until the queue drains).
        </li>
        <li>
          <strong className="text-foreground">Freshness</strong>: articles Check after 6 hours and Problem after 24; tweets and
          new IOCs Check after 24 hours and Problem after 72; the CVE check Check after 6 hours and Problem after 24;
          ATT&amp;CK Problem when a domain failed to sync and Check when a domain is more than 30 days old.
        </li>
        <li>
          <strong className="text-foreground">Coverage</strong>: how many articles (all time) name at least one country, threat
          actor or technique, and how many IOCs of each type were checked by at least one reputation provider (IOCs a provider
          cannot check, such as private IPs, do not count).
        </li>
        <li>
          <strong className="text-foreground">LLM</strong>: Problem when the latest model call failed (the row shows the HTTP
          status, error type, task and age); OK once a call succeeds again. Articles that could not be enriched because the
          model failed are parked and replayed automatically when the model works; the row counts how many are parked, how many
          are eligible for an automatic replay (attempt cap not reached and backoff elapsed) and how many were replayed
          automatically in 24 hours. The table compares each task over 24 hours and 7 days; a dash means no value was recorded.
        </li>
      </ul>
    </details>
  );
}
