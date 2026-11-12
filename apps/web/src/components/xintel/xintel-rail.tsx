import type { ReactNode } from "react";

import type { TweetStats } from "@/lib/api/loose-types";
import { periodTitle, type XIntelFilters } from "@/lib/xintel/filters";

function RailCard({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <section className="surface-raised rounded-lg p-5">
      <h2 className="font-heading text-base font-bold text-foreground">{title}</h2>
      <p className="mb-3 text-xs text-muted-foreground">{subtitle}</p>
      {children}
    </section>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-border py-2 text-sm first:border-t-0">
      <span className="min-w-0 truncate text-foreground">{label}</span>
      <span className="font-code text-sm font-semibold text-foreground">{value}</span>
    </div>
  );
}

/** Rail kanan X Intel: hitungan classifier, korban paling banyak disebut, akun paling aktif. Semuanya
 * mengikuti filter feed (stats memakai param yang sama). "–" selama stats belum ada. */
export function XIntelRail({
  stats,
  filters,
  onPickAccount,
}: {
  stats: TweetStats | undefined;
  filters: XIntelFilters;
  onPickAccount: (handle: string) => void;
}) {
  const title = periodTitle(filters);
  const period = title.toLowerCase();
  const n = (v: number | undefined) => (v === undefined ? "–" : v);
  const authors = (stats?.top_authors ?? []).slice(0, 5);
  const victims = (stats?.top_victims ?? []).slice(0, 5);

  return (
    <div className="flex flex-col gap-4">
      <RailCard title={title} subtitle={`What the classifier pulled from ${stats ? stats.total : "–"} posts`}>
        <Row label="Confirmed incidents" value={n(stats?.confirmed)} />
        <Row label="Mentions an APAC country" value={n(stats?.apac)} />
        <Row label="CVEs mentioned" value={n(stats?.with_cve)} />
        <Row label="Data breach claims" value={n(stats?.databreach)} />
        <Row label="Zero-days" value={n(stats?.zero_day)} />
        <Row label="OT / ICS related" value={n(stats?.ot)} />
      </RailCard>

      <RailCard title="Most-named victims" subtitle={`From victim names, ${period}`}>
        {!stats ? (
          <Row label="–" value="–" />
        ) : victims.length === 0 ? (
          <p className="text-sm text-muted-foreground">No victim named in this period</p>
        ) : (
          victims.map((v) => <Row key={v.victim} label={v.victim} value={v.count} />)
        )}
      </RailCard>

      <RailCard title="Most active accounts" subtitle="Top 5 by posts in this period">
        {!stats ? (
          <Row label="–" value="–" />
        ) : authors.length === 0 ? (
          <p className="text-sm text-muted-foreground">No posts in this period</p>
        ) : (
          authors.map((a) => (
            <button
              key={a.author}
              type="button"
              onClick={() => onPickAccount(a.author)}
              className="flex w-full items-baseline justify-between gap-3 rounded-md border-t border-border py-2 text-left text-sm outline-none first:border-t-0 hover:bg-surface focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              <span className="min-w-0 truncate font-code text-xs text-foreground">@{a.author}</span>
              <span className="font-code text-sm font-semibold text-foreground">{a.count}</span>
            </button>
          ))
        )}
      </RailCard>
    </div>
  );
}
