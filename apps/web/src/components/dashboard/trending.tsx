"use client";

import { PanelError } from "@/components/dashboard/stat-box";
import { TREND_KINDS, useDashboardTrending, type TrendItem } from "@/components/dashboard/use-dashboard-overview";
import { EntityChip } from "@/components/entities/entity-chip";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { periodInfo, type PeriodKey } from "@/lib/dashboard/period";
import { cn } from "@/lib/utils";

/** Tipe entity untuk resolve nama; aktor lewat id, malware dan CVE lewat nama (resolve). */
const ENTITY_TYPE: Record<TrendItem["kind"], string> = {
  actor: "intrusion-set",
  ttp: "attack-pattern", // TTP tidak diminta (TREND_KINDS), hanya melengkapi tipe
  malware: "malware,tool",
  cve: "vulnerability",
};

function kindWord(it: TrendItem): string {
  if (it.kind === "actor") return it.ransomware_group ? "Ransomware" : "Actor";
  return it.kind === "malware" ? "Malware" : "CVE";
}

/** Panel Trending (6.5): enam baris teratas aktor, malware dan CVE. `window_label` API tidak dirender. */
export function Trending({ period }: { period: PeriodKey }) {
  const q = useDashboardTrending(periodInfo(period).days, TREND_KINDS);
  const data = q.data;
  const items = data?.items.slice(0, 6) ?? [];

  return (
    <section className={cn(q.isPlaceholderData && "opacity-60")}>
      <h2 className="font-heading text-xl font-bold tracking-tight text-foreground">Trending</h2>
      {data && (
        <p className="mt-0.5 text-sm text-muted-foreground">
          {data.baseline_reliable
            ? `vs previous ${data.window_days} days`
            : `last ${data.window_days} days · not enough history to compare`}
        </p>
      )}
      <div className="mt-4">
        {q.isPending ? (
          <Skeleton aria-hidden className="h-56 w-full rounded-xl" />
        ) : q.isError ? (
          <PanelError title="Could not load trending" error={q.error} onRetry={() => void q.refetch()} />
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing is rising in this period.</p>
        ) : (
          <ul className="divide-y divide-border">
            {items.map((it) => (
              <li
                key={`${it.kind}:${it.entity_id ?? it.name}`}
                className="flex items-center gap-2 py-2.5"
              >
                <EntityChip type={ENTITY_TYPE[it.kind]} name={it.name} id={it.entity_id} />
                <Chip kind="flag" value={kindWord(it)} />
                {it.is_new && (
                  <Chip kind="status" value="action">
                    NEW
                  </Chip>
                )}
                <span className="ml-auto flex shrink-0 items-baseline gap-1.5">
                  <span className="font-code text-sm text-foreground">{it.count.toLocaleString("en-US")}</span>
                  {it.change_pct != null && !it.is_new && (
                    <span className="text-xs text-muted-foreground">+{it.change_pct}%</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
