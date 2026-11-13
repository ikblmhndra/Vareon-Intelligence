"use client";

import Link from "next/link";
import { Fragment, useState } from "react";

import { StatusBadge } from "@/components/scrapers/status-badge";
import { Chip } from "@/components/ui/chip";
import { MeterBar } from "@/components/ui/meter-bar";
import { SegmentedControl } from "@/components/ui/segmented-control";
import type { components } from "@/lib/api/schema";
import { TONE_STYLE, pct, queueTone } from "@/lib/data-health/tones";
import { byProblemSeverity, tickAge } from "@/lib/scrapers/health";

type Health = components["schemas"]["DataHealthOut"];

const WINDOWS = [
  { value: "last_24h", label: "24h" },
  { value: "last_7d", label: "7d" },
] as const;

// Urutan tetap; antrean yang tidak ada di peta dari API dicetak "–".
const QUEUES = ["scrape.rss", "scrape.api", "scrape.browser", "enrich", "notify", "maintenance", "cve"] as const;

const CARD = "surface-raised rounded-2xl p-5";

/** Alur scraper ke newsroom: angka jendela (24h / 7d) dari `pipeline`, angka "sekarang" dari antrean.
 * Pergantian jendela hanya memilih kunci lain dari data yang sudah ada (tanpa request). */
export function PipelineCard({ d }: { d: Health }) {
  const [win, setWin] = useState<(typeof WINDOWS)[number]["value"]>("last_24h");
  const w = d.pipeline[win];
  const depth = d.queues.enrich_depth;
  const max = d.queues.enrich_max_depth;
  const q = d.llm.queue;
  const sched = d.scrapers.scheduler;
  const e = d.enrichment;
  const depths = d.queues.depths;

  const steps: { name: string; value: string; sub?: string }[] = [
    { name: "SCRAPERS", value: `${w.items_found.toLocaleString()} items fetched` },
    { name: "DEDUP", value: `${w.items_new.toLocaleString()} new after seen-check` },
    { name: "ENRICH", value: `${depth === null ? "–" : depth.toLocaleString()} in queue now` },
    {
      name: "LLM JOBS",
      value: `${(q.pending_classify + q.pending_ttp).toLocaleString()} pending now`,
      sub: `classify ${q.pending_classify} · TTP ${q.pending_ttp}`,
    },
    { name: "NEWSROOM", value: `${w.articles_published.toLocaleString()} articles published` },
  ];

  const scheduler =
    sched.state === "ok"
      ? `alive · tick ${tickAge(sched.age_s)} ago`
      : sched.age_s === null
        ? "heartbeat missing"
        : `${sched.state.toUpperCase()} · last tick ${tickAge(sched.age_s)} ago`;

  return (
    <section className={`${CARD} lg:col-span-2`}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-heading text-xl font-bold tracking-tight text-foreground">Pipeline</h2>
          <p className="text-xs text-muted-foreground">From scraper to newsroom, left to right</p>
        </div>
        <SegmentedControl size="sm" aria-label="Pipeline window" options={WINDOWS} value={win} onChange={setWin} />
      </div>

      <ol className="flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.name}>
            {i > 0 && (
              <li aria-hidden className="self-center text-muted-foreground max-lg:rotate-90">
                →
              </li>
            )}
            <li className="min-w-0 flex-1 rounded-lg bg-surface px-3 py-2">
              <p className="text-2xs font-semibold tracking-wide text-muted-foreground uppercase">{s.name}</p>
              <p className="text-sm font-semibold text-foreground">{s.value}</p>
              {s.sub && <p className="font-code text-2xs text-muted-foreground">{s.sub}</p>}
            </li>
          </Fragment>
        ))}
      </ol>
      <p className="mt-2 text-2xs text-muted-foreground">
        Fetched and new count every item type (articles, IOCs, CVEs, posts) in the selected window; only articles pass
        through enrich. Queue and job figures are live.
      </p>

      <div className="mt-4">
        {depth === null ? (
          <p className="text-sm text-muted-foreground">Enrich queue depth unknown (Redis not reachable)</p>
        ) : (
          <MeterBar
            aria-label="Enrich queue depth"
            value={depth}
            max={max}
            tone={TONE_STYLE[queueTone(d.queues)]}
            label={`Enrich queue depth ${depth} / ${max} · backpressure at ${max}`}
          />
        )}
      </div>

      <dl className="mt-4 divide-y divide-border/70 text-sm">
        {[
          ["Scheduler (beat)", scheduler],
          [
            "Failed jobs 24 h",
            `${e.failed_24h.toLocaleString()} · 7 d: ${e.failed_7d.toLocaleString()} of ${e.processed_7d.toLocaleString()} processed (${pct(e.failed_7d, e.processed_7d)})`,
          ],
          ["Waiting for retry", e.pending_replay.toLocaleString()],
        ].map(([k, v]) => (
          <div key={k} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="text-right text-foreground tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>

      <h3 className="mt-4 mb-1 text-2xs font-semibold tracking-wide text-muted-foreground uppercase">
        Celery queues, depth now
      </h3>
      <ul className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
        {QUEUES.map((name) => (
          <li key={name} className="flex items-baseline justify-between gap-3 py-1 text-sm">
            <span className="font-code text-xs text-muted-foreground">{name}</span>
            <span className="font-code tabular-nums text-foreground">{depths?.[name] ?? "–"}</span>
          </li>
        ))}
      </ul>
      {depths === null && <p className="mt-1 text-xs text-muted-foreground">Redis not reachable</p>}
      <p className="mt-2 text-2xs text-muted-foreground">
        Messages waiting in the broker; tasks a worker already picked up are not counted.
      </p>
    </section>
  );
}

const MAX_ROWS = 8;

/** Scraper yang tidak ok dan tidak disabled. Satu baris = satu `<Link>` berisi teks dan chip saja (tanpa
 * kontrol bersarang); tujuan `/scrapers?scraper={id}` memilih barisnya dan membuka panelnya. */
export function NeedsAttentionCard({ scrapers }: { scrapers: Health["scrapers"] }) {
  const problems = byProblemSeverity(scrapers.problems);
  const total = Object.values(scrapers.counts).reduce((a, b) => a + b, 0);
  return (
    <section className={`${CARD} flex flex-col`}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="font-heading text-xl font-bold tracking-tight text-foreground">Needs attention</h2>
          <p className="text-xs text-muted-foreground">Scrapers not ok and not disabled</p>
        </div>
        <Chip kind="flag" value={String(problems.length)} />
      </div>

      {problems.length === 0 ? (
        <p className="text-sm text-muted-foreground">Every enabled scraper is OK.</p>
      ) : (
        <ul className="space-y-1">
          {problems.slice(0, MAX_ROWS).map((p) => (
            <li key={p.id}>
              <Link
                href={`/scrapers?scraper=${encodeURIComponent(p.id)}`}
                className="flex flex-wrap items-center gap-x-2 gap-y-0.5 rounded-md px-2 py-1.5 hover:bg-surface focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
              >
                <StatusBadge status={p.status} />
                <span className="font-code text-xs text-foreground">{p.id}</span>
                {p.consecutive_failing > 0 && (
                  <span className="text-2xs text-destructive-text">failing {p.consecutive_failing}/3</span>
                )}
                {p.reason && (
                  <span title={p.reason} className="min-w-0 basis-full truncate text-xs text-muted-foreground">
                    {p.reason}
                  </span>
                )}
              </Link>
            </li>
          ))}
          {problems.length > MAX_ROWS && (
            <li>
              <Link
                href="/scrapers"
                className="block rounded-md px-2 py-1.5 text-xs text-primary-text underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
              >
                and {problems.length - MAX_ROWS} more on Scrapers
              </Link>
            </li>
          )}
        </ul>
      )}

      <div className="mt-auto pt-4">
        <p className="text-xs text-muted-foreground">
          Fleet: {total} scrapers · {scrapers.counts.ok ?? 0} ok · {scrapers.counts.disabled ?? 0} disabled
        </p>
        <Link
          href="/scrapers"
          className="mt-1 inline-block rounded-sm text-sm font-medium text-primary-text underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
        >
          Open Scrapers
        </Link>
      </div>
    </section>
  );
}
