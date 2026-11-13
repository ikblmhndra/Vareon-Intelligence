"use client";

import { ToneChip } from "@/components/data-health/tone-chip";
import { MeterBar } from "@/components/ui/meter-bar";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { components } from "@/lib/api/schema";
import { statusTone } from "@/components/scrapers/status-badge";
import { pct, type FreshnessRow } from "@/lib/data-health/tones";
import { fmtCompactAge, fmtDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

type Health = components["schemas"]["DataHealthOut"];

const CARD = "surface-raised rounded-2xl p-5";
const H2 = "font-heading text-xl font-bold tracking-tight text-foreground";

/** Lima baris kesegaran dari `freshnessRows`; ambang pada caption berasal dari baris itu sendiri. */
export function FreshnessCard({
  rows,
  monitorX,
  nowMs,
}: {
  rows: FreshnessRow[];
  monitorX: { status: string; reason?: string | null } | undefined;
  nowMs: number;
}) {
  return (
    <section className={CARD}>
      <h2 className={cn(H2, "mb-3")}>Source freshness</h2>
      <ul className="divide-y divide-border/70">
        {rows.map((r) => (
          <li key={r.key} className="py-2">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm text-muted-foreground">{r.label}</p>
                {r.state === "loading" ? (
                  <Skeleton className="mt-1 h-5 w-16" />
                ) : r.state === "failed" ? (
                  <p className="text-sm text-foreground">unknown (failed to load)</p>
                ) : r.at ? (
                  <p title={fmtDateTime(r.at)} className="font-code text-sm text-foreground tabular-nums">
                    {fmtCompactAge(r.at, nowMs)}
                  </p>
                ) : (
                  <p className="text-sm text-foreground">never</p>
                )}
                <p className="text-2xs text-muted-foreground">{r.caption}</p>
                {r.key === "tweet" && monitorX && (
                  <p className={cn("text-2xs", statusTone(monitorX.status) === "bad" ? "text-destructive-text" : "text-warning-text")}>
                    <span className="font-code">monitor_x</span> {monitorX.status.replace("_", " ")}
                    {monitorX.reason ? `: ${monitorX.reason}` : ""}
                  </p>
                )}
              </div>
              <ToneChip tone={r.tone} />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

type Dashboard = { total_articles: number; coverage: { with_country: number; with_actor: number; with_ttp: number } };

export function CoverageCard({
  dashboard,
  failed,
  iocEnrichment,
}: {
  dashboard: Dashboard | undefined;
  failed: boolean;
  iocEnrichment: Health["ioc_enrichment"];
}) {
  const rows: [string, number | undefined][] = [
    ["Articles with a country", dashboard?.coverage.with_country],
    ["Articles with a threat actor", dashboard?.coverage.with_actor],
    ["Articles with an ATT&CK technique", dashboard?.coverage.with_ttp],
  ];
  return (
    <section className={CARD}>
      <h2 className={cn(H2, "mb-3")}>Coverage</h2>
      <dl className="divide-y divide-border/70">
        {rows.map(([label, n]) => (
          <div key={label} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2">
            <dt className="text-sm text-muted-foreground">{label}</dt>
            <dd className="text-right text-sm text-foreground tabular-nums">
              {dashboard && n !== undefined ? (
                `${n.toLocaleString()} · ${pct(n, dashboard.total_articles)}`
              ) : failed ? (
                "unknown (failed to load)"
              ) : (
                <Skeleton className="h-4 w-16" />
              )}
            </dd>
          </div>
        ))}
      </dl>
      <h3 className="mt-4 mb-1 text-2xs font-semibold tracking-wide text-muted-foreground uppercase">
        IOC reputation checks
      </h3>
      {iocEnrichment.length === 0 ? (
        <p className="text-sm text-muted-foreground">No IOCs yet.</p>
      ) : (
        <ul className="space-y-2">
          {iocEnrichment.map((c) => (
            <li key={c.type}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="font-code text-xs text-muted-foreground">{c.type}</span>
                <span className="text-foreground tabular-nums">
                  {c.enriched.toLocaleString()} / {c.total.toLocaleString()}
                </span>
              </div>
              <MeterBar aria-label={`${c.type} checked`} value={c.enriched} max={c.total} tone="primary" className="mt-1" />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

type Story = Health["llm"]["stories_24h"];
const STORY_ROWS: [string, keyof Story][] = [
  ["New stories", "new_stories"],
  ["Follow-ups", "followups"],
  ["Inherited classify", "inherited"],
  ["Matched by embedding", "by_embedding"],
  ["LLM calls avoided", "llm_calls_avoided"],
];

export function StoriesCard({ day, week }: { day: Story; week: Story }) {
  return (
    <section className={CARD}>
      <h2 className={cn(H2, "mb-3")}>Stories</h2>
      <Table className="table-fixed">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="h-8 w-[52%] px-2 text-2xs">
              <span className="sr-only">Metric</span>
            </TableHead>
            <TableHead className="h-8 w-[24%] px-2 text-right text-2xs">24 H</TableHead>
            <TableHead className="h-8 w-[24%] px-2 text-right text-2xs">7 D</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {STORY_ROWS.map(([label, k]) => (
            <TableRow key={k}>
              <TableCell className="px-2 py-1.5 text-sm text-muted-foreground">{label}</TableCell>
              <TableCell className="px-2 py-1.5 text-right text-sm tabular-nums">{day[k].toLocaleString()}</TableCell>
              <TableCell className="px-2 py-1.5 text-right text-sm tabular-nums">{week[k].toLocaleString()}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="mt-2 text-2xs text-muted-foreground">
        Inherited follow-ups skip both classify and TTP extraction (2 calls each).
      </p>
    </section>
  );
}
