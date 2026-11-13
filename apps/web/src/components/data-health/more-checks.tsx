"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { ToneChip } from "@/components/data-health/tone-chip";
import { Disclosure } from "@/components/ui/disclosure";
import type { components } from "@/lib/api/schema";
import { TONE_LABEL, pct, type Tone } from "@/lib/data-health/tones";
import { fmtAgo, fmtDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

type Health = components["schemas"]["DataHealthOut"];

const CARD = "surface-raised rounded-2xl p-5";
const H3 = "mb-3 font-heading text-xl font-bold tracking-tight text-foreground";

function Row({ label, value, title, tone }: { label: string; value: ReactNode; title?: string; tone?: Tone }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="flex min-w-0 items-baseline gap-2 text-right text-sm text-foreground tabular-nums">
        <span className="min-w-0 break-words" title={title}>
          {value}
        </span>
        {tone && <ToneChip tone={tone} />}
      </dd>
    </div>
  );
}

/** "3 h ago" dengan `title` waktu lengkap; kosong = "never". */
function Ago({ iso, nowMs }: { iso: string | null | undefined; nowMs: number }) {
  if (!iso || Number.isNaN(Date.parse(iso))) return <>never</>;
  return <span title={fmtDateTime(iso)}>{fmtAgo(iso, nowMs)}</span>;
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={CARD}>
      <h3 className={H3}>{title}</h3>
      <dl className="divide-y divide-border/70">{children}</dl>
    </section>
  );
}

/** Tiga pemeriksaan sekunder. Terlipat secara bawaan; terbuka sejak render pertama bila CVE ingest atau
 * Sigma tidak OK (`defaultOpen` hanya dibaca saat mount, jadi refetch tidak membuka/menutupnya lagi).
 * Chip nada tetap tampil saat terlipat; `printOpen` menjaga isinya ikut tercetak. */
export function MoreChecks({
  d,
  tones,
  nowMs,
}: {
  d: Health;
  tones: { cve: Tone; sigma: Tone; failed: Tone };
  nowMs: number;
}) {
  const { enrichment: e, queues: q, cve_ingest: ingest, sigma } = d;
  const report = ingest.last_reconcile;
  const n = (v: unknown) => Number(v ?? 0).toLocaleString();
  const chips: [string, Tone][] = [
    ["CVE INGEST", tones.cve],
    ["SIGMA", tones.sigma],
    ["ENRICHMENT", tones.failed],
  ];
  return (
    <Disclosure
      className="mb-4"
      printOpen
      headingLevel={2}
      defaultOpen={tones.cve === "warn" || tones.cve === "bad" || tones.sigma === "warn" || tones.sigma === "bad"}
      title={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-heading text-xl font-bold tracking-tight">More checks</span>
          {chips.map(([name, t]) => (
            <ToneChip key={name} tone={t}>
              {name} {TONE_LABEL[t]}
            </ToneChip>
          ))}
        </span>
      }
    >
      <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="CVE ingest">
          {!ingest.enabled ? (
            <Row label="Mirror" value="Off (CVE_MIRROR__ENABLED is false)" />
          ) : (
            <>
              <Row label="Promote mode" value={ingest.promote} />
              <Row
                label="Last sync"
                value={<Ago iso={ingest.last_sync_at} nowMs={nowMs} />}
                tone={ingest.status === "red" ? "bad" : "ok"}
              />
              <Row label="Pending items" value={ingest.pending.toLocaleString()} />
              <Row label="Last reconcile" value={<Ago iso={ingest.last_reconcile_at} nowMs={nowMs} />} />
              {report && (
                <Row
                  label="Reconcile result"
                  value={
                    report.status === "error"
                      ? `error · ${String(report.error || "unknown")}`
                      : `${n(report.fixed)} fixed · ${n(report.missing)} missing · ${n(report.outdated)} outdated · ${n(report.failed)} failed`
                  }
                  tone={report.status === "error" ? "warn" : undefined}
                />
              )}
            </>
          )}
        </Card>
        <Card title="Sigma rules">
          <Row label="Release" value={sigma.release ?? "none loaded"} />
          <Row label="Rules" value={sigma.rules.toLocaleString()} tone={sigma.rules ? "ok" : "bad"} />
          <Row label="Fetched" value={<Ago iso={sigma.fetched_at} nowMs={nowMs} />} />
          {sigma.last_error && <Row label="Last error" value={sigma.last_error} tone="warn" />}
        </Card>
        <Card title="Enrichment detail">
          <Row label="Failed jobs created, last 24 hours" value={e.failed_24h.toLocaleString()} />
          <Row
            label="Failed jobs created, last 7 days"
            value={`${e.failed_7d.toLocaleString()} of ${e.processed_7d.toLocaleString()} processed (${pct(e.failed_7d, e.processed_7d)}) · snapshot of jobs still failed`}
          />
          <Row
            label="Failed jobs waiting for a retry"
            value={e.pending_replay.toLocaleString()}
            tone={e.pending_replay ? "warn" : "ok"}
          />
          <Row label="Newest failed job created" value={<Ago iso={e.last_failure_at} nowMs={nowMs} />} />
          <Row
            label="Enrich queue"
            value={
              q.enrich_depth === null
                ? "unknown (Redis not reachable)"
                : `${q.enrich_depth.toLocaleString()} waiting · backpressure at ${q.enrich_max_depth.toLocaleString()}`
            }
          />
          <Link
            href="/newsroom"
            className={cn(
              "mt-3 inline-block rounded-sm text-sm font-medium text-primary-text underline-offset-4 hover:underline",
              "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none",
            )}
          >
            Review jobs in Newsroom › Filtered Articles › Enrichment queue
          </Link>
        </Card>
      </div>
    </Disclosure>
  );
}
