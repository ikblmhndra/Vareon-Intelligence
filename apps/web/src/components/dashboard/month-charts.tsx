"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";

import { ChartCard, PanelError } from "@/components/dashboard/stat-box";
import {
  useDashboardRansomware,
  useDashboardStats,
} from "@/components/dashboard/use-dashboard-overview";
import { EntityChip } from "@/components/entities/entity-chip";
import { BarSeries } from "@/components/ui/bar-series";
import { MeterBar } from "@/components/ui/meter-bar";
import { SHARE_BAR_SEGMENT, ShareBar } from "@/components/ui/share-bar";
import { Skeleton } from "@/components/ui/skeleton";
import { entityHref } from "@/lib/entities/types";
import { fmtShortDate, parseLocalDate } from "@/lib/format";
import { cn } from "@/lib/utils";

const DAYS = 30;
const BODY_HEIGHT = 220;

const num = (n: number) => n.toLocaleString("en-US");
const titleCase = (s: string) => s.replace(/\b\w/g, (c) => c.toUpperCase());
const linkClass =
  "rounded-sm hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background outline-none";

/** Tanggal lokal -> "YYYY-MM-DD" tanpa lewat UTC (toISOString menggeser hari di zona timur UTC). */
function isoLocal(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** 30 tanggal berakhir pada bagian tanggal `generated_at`; dibangun dari `parseLocalDate`, bukan `new Date(iso)`. */
function lastDates(generatedAt: string): string[] {
  const end = parseLocalDate(generatedAt.slice(0, 10));
  return Array.from({ length: DAYS }, (_, i) =>
    isoLocal(new Date(end.getFullYear(), end.getMonth(), end.getDate() - (DAYS - 1 - i))),
  );
}

/** Persen dari total yang ditampilkan. Largest-remainder: lantai tiap baris, sisa poin ke pecahan terbesar, supaya
 * tidak ada baris negatif/0% semu dan kolom pas 100 (menaruh sisa di baris terakhir bisa menghasilkan "-1%"). */
function percents(values: number[]): number[] {
  const total = values.reduce((a, b) => a + b, 0);
  if (total <= 0) return values.map(() => 0);
  const exact = values.map((v) => (v / total) * 100);
  const out = exact.map(Math.floor);
  let left = 100 - out.reduce((a, b) => a + b, 0);
  exact
    .map((x, i) => ({ i, frac: x - Math.floor(x) }))
    .sort((a, b) => b.frac - a.frac || a.i - b.i)
    .forEach(({ i }) => {
      if (left-- > 0) out[i] += 1;
    });
  return out;
}

const Empty = ({ children }: { children: ReactNode }) => (
  <p className="flex h-full items-center justify-center text-center text-sm text-muted-foreground">{children}</p>
);

export function MonthCharts({ threatOnly }: { threatOnly: boolean }) {
  const stats = useDashboardStats(DAYS, threatOnly);
  const ransom = useDashboardRansomware(DAYS);
  const [allTtps, setAllTtps] = useState(false);

  const dim = (q: { isPlaceholderData: boolean }) => (q.isPlaceholderData ? "opacity-60" : undefined);
  const skeleton = <Skeleton aria-hidden className="h-full w-full rounded-xl" />;
  const statsErr = (title: string) => (
    <PanelError title={title} error={stats.error} onRetry={() => void stats.refetch()} className="h-full" />
  );
  const d = stats.data;

  // Insiden per hari
  let incidents: ReactNode = null;
  if (stats.isPending) incidents = skeleton;
  else if (stats.isError && !d) incidents = statsErr("Could not load incidents per day");
  else if (d) {
    const byDate = new Map(d.timeline.map((t) => [t.date, t.incidents]));
    const dates = lastDates(d.generated_at);
    const values = dates.map((x) => byDate.get(x) ?? 0);
    const top = new Set(
      values
        .map((v, i) => ({ v, i }))
        .filter((x) => x.v > 0)
        .sort((a, b) => b.v - a.v || b.i - a.i)
        .slice(0, 3)
        .map((x) => x.i),
    );
    const labels = dates.map((x) => fmtShortDate(parseLocalDate(x)));
    incidents =
      top.size === 0 ? (
        <Empty>No confirmed incident in the last 30 days.</Empty>
      ) : (
        <div className={dim(stats)}>
          <BarSeries
            labels={labels}
            values={values}
            highlight={(i) => top.has(i)}
            tone="neutral"
            highlightTone="destructive"
            height={BODY_HEIGHT}
            tickEvery={10}
            aria-label="Confirmed incidents per day, last 30 days"
          />
          <p className="sr-only">
            Highest:{" "}
            {[...top]
              .sort((a, b) => values[b] - values[a] || b - a)
              .map((i) => `${labels[i]} ${values[i]}`)
              .join(", ")}
          </p>
        </div>
      );
  }

  // Ransomware per grup
  let groups: ReactNode = null;
  if (ransom.isPending) groups = skeleton;
  else if (ransom.isError && !ransom.data)
    groups = (
      <PanelError
        title="Could not load ransomware groups"
        error={ransom.error}
        onRetry={() => void ransom.refetch()}
        className="h-full"
      />
    );
  else if (ransom.data) {
    const rows = ransom.data.top_groups.slice(0, 5);
    const other = ransom.data.total - rows.reduce((a, r) => a + r.count, 0);
    const max = Math.max(1, ...rows.map((r) => r.count));
    groups =
      rows.length === 0 ? (
        <Empty>No victim in the last 30 days.</Empty>
      ) : (
        <ul className={cn("flex flex-col gap-2.5", dim(ransom))}>
          {rows.map((r) => (
            <li key={r.name} className="flex items-center gap-3">
              <EntityChip type="intrusion-set" name={r.name} className="w-40 shrink-0" />
              <MeterBar value={r.count} max={max} tone="destructive" aria-label={`${r.name}: ${r.count} victims`} className="min-w-0 flex-1" />
              <span className="w-10 shrink-0 text-right font-code text-xs text-foreground">{num(r.count)}</span>
            </li>
          ))}
          {other > 0 && (
            <li className="flex items-center gap-3 text-xs text-muted-foreground">
              <span className="w-40 shrink-0 px-2">Other</span>
              <span className="min-w-0 flex-1" />
              <span className="w-10 shrink-0 text-right font-code">{num(other)}</span>
            </li>
          )}
        </ul>
      );
  }

  // Industri
  let industries: ReactNode = null;
  if (stats.isPending) industries = skeleton;
  else if (stats.isError && !d) industries = statsErr("Could not load targeted industries");
  else if (d) {
    const all = d.top_industries.filter((x) => x.name.toLowerCase() !== "general");
    const head = all.slice(0, 4);
    const rest = all.slice(4).reduce((a, x) => a + x.count, 0);
    const rows = [
      ...head.map((x) => ({ name: x.name, label: titleCase(x.name), value: x.count, link: true })),
      ...(rest > 0 ? [{ name: "Other", label: "Other", value: rest, link: false }] : []),
    ];
    const pct = percents(rows.map((r) => r.value));
    industries =
      rows.length === 0 ? (
        <Empty>No sector was mentioned in the last 30 days.</Empty>
      ) : (
        <div className={cn("flex flex-col gap-3", dim(stats))}>
          <ShareBar items={rows.map((r) => ({ label: r.label, value: r.value }))} aria-label="Targeted industries" />
          <ul className="flex flex-col gap-1.5 text-xs">
            {rows.map((r, i) => (
              <li key={r.name} className="flex items-center gap-2">
                <span aria-hidden className={cn("size-2.5 shrink-0 rounded-sm", SHARE_BAR_SEGMENT[i])} />
                {r.link ? (
                  <Link href={entityHref({ type: "identity", name: r.name })} className={cn("min-w-0 flex-1 truncate text-foreground", linkClass)}>
                    {r.label}
                  </Link>
                ) : (
                  <span className="min-w-0 flex-1 truncate text-foreground">{r.label}</span>
                )}
                <span className="font-code text-muted-foreground">{pct[i]}%</span>
              </li>
            ))}
          </ul>
          {d.industry_unspecified > 0 && (
            <p className="text-2xs text-muted-foreground">
              {num(d.industry_unspecified)} articles without a specific sector are not counted.
            </p>
          )}
        </div>
      );
  }

  // Teknik
  let techniques: ReactNode = null;
  if (stats.isPending) techniques = skeleton;
  else if (stats.isError && !d) techniques = statsErr("Could not load top techniques");
  else if (d) {
    const all = d.top_ttps.slice(0, 10);
    const shown = allTtps ? all : all.slice(0, 5);
    const max = Math.max(1, all[0]?.count ?? 1);
    techniques = (
      <div className={cn("flex h-full flex-col gap-2 overflow-y-auto", dim(stats))}>
        <ul className="flex flex-col gap-2">
          {shown.map((t) => {
            const at = t.name.indexOf(" — ");
            const id = at < 0 ? t.name : t.name.slice(0, at);
            const name = at < 0 ? "" : t.name.slice(at + 3);
            return (
              <li key={t.name} className="flex items-center gap-2 text-xs">
                <Link href={entityHref({ type: "attack-pattern", name: id })} className={cn("w-16 shrink-0 font-code text-foreground", linkClass)}>
                  {id}
                </Link>
                <span className="min-w-0 flex-1 truncate text-muted-foreground" title={name}>{name}</span>
                <MeterBar value={t.count} max={max} tone="primary" aria-label={`${t.name}: ${t.count}`} className="w-12 shrink-0" />
                <span className="w-8 shrink-0 text-right font-code text-foreground">{num(t.count)}</span>
              </li>
            );
          })}
        </ul>
        {all.length > 5 && (
          <button
            type="button"
            aria-expanded={allTtps}
            onClick={() => setAllTtps((v) => !v)}
            className={cn("self-start text-xs font-medium text-primary", linkClass)}
          >
            {allTtps ? "Show 5" : `Show all ${all.length}`}
          </button>
        )}
        <p className="text-2xs text-muted-foreground">
          {num(d.coverage.with_ttp)} of {num(d.total_articles)} articles map to a technique.
        </p>
      </div>
    );
  }

  return (
    <section className="flex flex-col gap-4">
      <div>
        <h2 className="font-heading text-xl font-bold tracking-tight text-foreground">The month in charts</h2>
        <p className="text-sm text-muted-foreground">
          Last 30 days · all sources{threatOnly ? " · threat news only" : ""}
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <ChartCard title="Incidents per day" note="Confirmed, 30 days" height={BODY_HEIGHT}>
          {incidents}
        </ChartCard>
        <ChartCard title="Ransomware by group" note="Victims, 30 days" height={BODY_HEIGHT}>
          {groups}
        </ChartCard>
        <ChartCard title="Targeted industries" note="Share of sector mentions" height={BODY_HEIGHT}>
          {industries}
        </ChartCard>
        <ChartCard
          title="Top techniques"
          note={threatOnly ? "Mentions in threat news" : "Mentions in articles"}
          height={BODY_HEIGHT}
        >
          {techniques}
        </ChartCard>
      </div>
    </section>
  );
}
