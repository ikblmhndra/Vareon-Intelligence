"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { ClustersResponse, SpikesResponse } from "@/lib/api/loose-types";

function ClusterSparkline({ articles }: { articles: { posted_on: string }[] }) {
  const dates = articles.map((a) => (a.posted_on ? new Date(a.posted_on).getTime() : null)).filter((v): v is number => v != null).sort((a, b) => a - b);
  if (dates.length < 2) return null;
  return (
    <svg width={64} height={12} className="mr-1.5 inline-block align-middle">
      <line x1={2} y1={6} x2={62} y2={6} stroke="var(--border)" strokeWidth={1} />
      {dates.map((d, i) => {
        const min = dates[0];
        const max = dates[dates.length - 1];
        const x = min === max ? 32 : Math.round(2 + ((d - min) / (max - min)) * 60);
        return <circle key={i} cx={x} cy={6} r={1.5} fill="var(--primary)" opacity={0.7} />;
      })}
    </svg>
  );
}

/** Port sub-view "Clusters" Pipeline 1 (`intel.js:31-148`) -- TF-IDF
 * greedy clustering SEDERHANA, manual-generate ONLY (legacy: "do not
 * auto-load on tab switch"), beda dari Campaigns Pipeline 2 yang
 * auto-load + enrichment kaya. */
export function SimpleClustersPanel() {
  const [days, setDays] = useState(30);
  const [threshold, setThreshold] = useState(0.35);
  const [exclLowRel, setExclLowRel] = useState(false);
  const [showSingle, setShowSingle] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [triggerKey, setTriggerKey] = useState(0);
  const [hasGenerated, setHasGenerated] = useState(false);

  const query = useQuery({
    queryKey: ["campaign-clusters", "simple-clusters", days, threshold, exclLowRel, triggerKey],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/clusters", {
        params: { query: { days, threshold, exclude_low_reliability: exclLowRel } },
      });
      if (error) throw error;
      return data as unknown as ClustersResponse;
    },
    enabled: hasGenerated,
  });

  const spikeQuery = useQuery({
    queryKey: ["campaign-clusters", "spikes-for-clusters"],
    queryFn: async () => {
      // `lookback_days` minimum backend BARU 14 (Grup G1's Early
      // Warning, `Query(30, ge=14, le=90)`) -- legacy literal 7
      // (`intel.js:118`) sekarang INVALID (422), dipakai nilai
      // minimum valid terdekat.
      const { data, error } = await api.GET("/api/spikes", { params: { query: { lookback_days: 14, z_threshold: 2.0 } } });
      if (error) throw error;
      return data as unknown as SpikesResponse;
    },
    enabled: hasGenerated,
  });

  const spikeEntities = new Set(
    [...(spikeQuery.data?.threat_actors ?? []), ...(spikeQuery.data?.countries ?? [])]
      .map((s) => s.entity?.toLowerCase())
      .filter((v): v is string => Boolean(v)),
  );

  function matchesSpike(clusterName: string, articles: { title: string }[]): boolean {
    if (spikeEntities.size === 0) return false;
    const hay = (clusterName + " " + articles.map((a) => a.title).join(" ")).toLowerCase();
    return [...spikeEntities].some((e) => hay.includes(e));
  }

  function generate() {
    setHasGenerated(true);
    setTriggerKey((k) => k + 1);
  }

  const clusters = (query.data?.clusters ?? []).filter((c) => showSingle || c.source_count > 1);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-2 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Days</Label>
          <Input type="number" aria-label="Days" min={7} max={90} value={days} onChange={(e) => setDays(Number(e.target.value) || 30)} className="w-20 font-mono text-xs" />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Threshold</Label>
          <Input
            type="number" aria-label="Threshold"
            min={0.2}
            max={0.7}
            step={0.05}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value) || 0.35)}
            className="w-24 font-mono text-xs"
          />
        </div>
        <label className="flex items-center gap-1.5 pb-1.5 font-mono text-xs text-muted-foreground">
          <Checkbox checked={exclLowRel} onCheckedChange={(v) => setExclLowRel(v === true)} />
          Exclude low-reliability sources
        </label>
        <label className="flex items-center gap-1.5 pb-1.5 font-mono text-xs text-muted-foreground">
          <Checkbox checked={showSingle} onCheckedChange={(v) => setShowSingle(v === true)} />
          Show single-source
        </label>
        <Button size="sm" onClick={generate} disabled={query.isFetching}>
          {query.isFetching ? "Clustering…" : "Generate"}
        </Button>
        {query.data && <span className="ml-auto font-mono text-xs text-muted-foreground">{clusters.length} news cluster(s) found</span>}
      </div>

      {!hasGenerated && <p className="py-10 text-center text-xs text-muted-foreground">Set parameters and click Generate to cluster recent articles.</p>}
      {hasGenerated && query.isFetching && <p className="py-10 text-center text-xs text-muted-foreground">Clustering articles… (first load may take a few seconds)</p>}
      {hasGenerated && query.isError && <p className="py-10 text-center text-xs text-destructive">Error loading clusters.</p>}
      {hasGenerated && query.data && clusters.length === 0 && <p className="py-10 text-center text-xs text-muted-foreground">No multi-source clusters found for selected window.</p>}

      <div className="flex flex-col gap-2">
        {clusters.map((c) => {
          const isOpen = expanded[c.cluster_id];
          const spike = matchesSpike(c.cluster_name, c.articles);
          return (
            <div key={c.cluster_id} className="rounded-xl border border-border bg-background">
              <button
                type="button"
                onClick={() => setExpanded((e) => ({ ...e, [c.cluster_id]: !e[c.cluster_id] }))}
                className="flex w-full flex-wrap items-center gap-1.5 px-3 py-2 text-left"
              >
                <span className="text-muted-foreground">{isOpen ? "▼" : "▶"}</span>
                <span className="text-sm font-semibold text-foreground">{c.cluster_name}</span>
                <ClusterSparkline articles={c.articles} />
                {c.first_date !== c.last_date && (
                  <span className="font-mono text-xs text-muted-foreground">
                    {c.first_date} → {c.last_date}
                  </span>
                )}
                <span className="flex flex-wrap gap-1">
                  {c.sources.map((s) => (
                    <span key={s} className="rounded-full border border-border bg-surface px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                      {s}
                    </span>
                  ))}
                </span>
                <span
                  className={cn(
                    "rounded-full border px-1.5 py-0.5 font-mono text-xs uppercase",
                    c.confidence === "high" ? "border-success/40 bg-success/10 text-success-text" : c.confidence === "medium" ? "border-warning/40 bg-warning/10 text-warning-text" : "border-border text-muted-foreground",
                  )}
                >
                  {c.source_count} source{c.source_count !== 1 ? "s" : ""}
                </span>
                <span className="rounded-full border border-border bg-surface px-1.5 py-0.5 font-mono text-xs text-muted-foreground">{c.article_count} articles</span>
                {spike && <span className="rounded-full border border-destructive/40 bg-destructive/10 px-1.5 py-0.5 font-mono text-xs text-destructive-text">⚡ Active Spike</span>}
                {c.re_emerged && <span className="rounded-full border border-primary/40 bg-primary/10 px-1.5 py-0.5 font-mono text-xs text-primary-text">↑ Re-emerging</span>}
              </button>
              {isOpen && (
                <div className="border-t border-border">
                  {c.articles.map((a) => (
                    <a key={a.id} href={a.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 border-b border-border px-3 py-2 text-xs last:border-b-0 hover:bg-accent">
                      <span className="flex-1 truncate text-foreground">{a.title}</span>
                      <span className="font-mono text-xs text-muted-foreground">{a.source}</span>
                      <span className="font-mono text-xs text-muted-foreground">{a.posted_on}</span>
                    </a>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
