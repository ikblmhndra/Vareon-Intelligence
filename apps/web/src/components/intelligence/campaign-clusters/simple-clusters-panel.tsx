"use client";

import { useId, useState, type ReactNode } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { useDebounced } from "@/lib/cve/catalog";
import { fmtShortDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Notice } from "@/components/ui/notice";
import { PresetControl } from "@/components/ui/preset-control";
import { StatePanel } from "@/components/ui/state-panel";
import { Switch } from "@/components/ui/switch";
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

const DAYS_PRESETS = [
  { value: 7, label: "7d" },
  { value: 14, label: "14d" },
  { value: 30, label: "30d" },
];
const THRESHOLD_MIN = 0.2;
const THRESHOLD_MAX = 0.7;

/** Clusters (Simple, Pipeline 1 `intel.js:31-148`): TF-IDF greedy sederhana. Legacy manual-generate;
 * sejak 2b (D12) dimuat otomatis saat mount dan tiap parameter berubah (debounce 500 ms), tanpa tombol
 * Generate. Rentang threshold API tak berubah (D11). */
export function SimpleClustersPanel({ tabs }: { tabs: ReactNode }) {
  const thresholdId = useId();
  const [days, setDays] = useState(30);
  const [threshold, setThreshold] = useState(0.35);
  const [draft, setDraft] = useState("0.35");
  const [thresholdError, setThresholdError] = useState<string>();
  const [exclLowRel, setExclLowRel] = useState(false);
  const [showSingle, setShowSingle] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  // Satu request per jeda 500 ms, bukan per ketikan/klik.
  const params = useDebounced({ days, threshold, exclLowRel }, 500);

  const query = useQuery({
    queryKey: ["campaign-clusters", "simple-clusters", params.days, params.threshold, params.exclLowRel],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/clusters", {
        params: { query: { days: params.days, threshold: params.threshold, exclude_low_reliability: params.exclLowRel } },
      });
      if (error) throw error;
      return data as unknown as ClustersResponse;
    },
    // Hasil lama tetap tampil saat parameter baru dimuat, jadi daftar tak berkedip kosong.
    placeholderData: keepPreviousData,
  });

  const spikeQuery = useQuery({
    queryKey: ["campaign-clusters", "spikes-for-clusters"],
    queryFn: async () => {
      // `lookback_days` minimum backend 14 (Early Warning, `Query(30, ge=14, le=90)`) -- legacy literal 7
      // (`intel.js:118`) sekarang 422, dipakai nilai minimum valid terdekat.
      const { data, error } = await api.GET("/api/spikes", { params: { query: { lookback_days: 14, z_threshold: 2.0 } } });
      if (error) throw error;
      return data as unknown as SpikesResponse;
    },
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

  // Seperti PresetControl: nilai di luar rentang API tak pernah jadi query; galat tampil dan nilai lama bertahan.
  function commitThreshold(text: string) {
    setDraft(text);
    const n = text.trim() === "" ? Number.NaN : Number(text);
    if (!Number.isFinite(n) || n < THRESHOLD_MIN || n > THRESHOLD_MAX) {
      setThresholdError("Enter a value from 0.20 to 0.70.");
      return;
    }
    setThresholdError(undefined);
    setThreshold(n);
  }

  const clusters = (query.data?.clusters ?? []).filter((c) => showSingle || c.source_count > 1);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
        <div className="self-end">{tabs}</div>
        <PresetControl label="Days" aria-label="Days" presets={DAYS_PRESETS} value={days} onChange={setDays} min={7} max={90} />
        <Field label="Similarity threshold" htmlFor={thresholdId} hint="Higher means tighter clusters." error={thresholdError} className="w-44">
          <Input
            id={thresholdId}
            type="number"
            inputMode="decimal"
            min={THRESHOLD_MIN}
            max={THRESHOLD_MAX}
            step={0.05}
            value={draft}
            aria-invalid={!!thresholdError}
            aria-describedby={fieldDescribedBy(thresholdId, { hint: "Higher means tighter clusters.", error: thresholdError })}
            onChange={(e) => commitThreshold(e.target.value)}
            className="h-8 text-xs"
          />
        </Field>
        <div className="flex flex-col gap-2 pt-1">
          <Switch checked={exclLowRel} onCheckedChange={setExclLowRel} aria-label="Exclude low-reliability sources" label="Exclude low-reliability sources" />
          <Switch checked={showSingle} onCheckedChange={setShowSingle} aria-label="Show single-source clusters" label="Show single-source" />
        </div>
        {query.data && <span className="ml-auto self-end text-xs text-muted-foreground">{clusters.length} news cluster(s) found</span>}
      </div>

      {query.isFetching && !query.data && <Notice busy tone="info" title="Clustering may take a few seconds" />}
      {query.isError && (
        <StatePanel
          variant="error"
          title="Failed to load clusters"
          action={
            <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
              Retry
            </Button>
          }
        />
      )}
      {query.data && clusters.length === 0 && (
        <StatePanel variant="empty" title="No multi-source clusters found" description="Try a longer window or a lower threshold, or show single-source clusters." />
      )}

      <div className="flex flex-col gap-2">
        {clusters.map((c) => {
          const isOpen = expanded[c.cluster_id];
          const spike = matchesSpike(c.cluster_name, c.articles);
          const shownSources = c.sources.slice(0, 3);
          const moreSources = c.sources.length - shownSources.length;
          return (
            <div key={c.cluster_id} className="rounded-lg border border-border bg-background">
              <button
                type="button"
                aria-expanded={!!isOpen}
                onClick={() => setExpanded((e) => ({ ...e, [c.cluster_id]: !e[c.cluster_id] }))}
                className="flex w-full flex-wrap items-center gap-2 rounded-lg px-4 py-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                <span aria-hidden="true" className="text-muted-foreground">{isOpen ? "▼" : "▶"}</span>
                <span className="text-sm font-semibold text-foreground">{c.cluster_name}</span>
                <ClusterSparkline articles={c.articles} />
                {c.first_date !== c.last_date && (
                  <span className="text-2xs text-muted-foreground">
                    {fmtShortDate(c.first_date)} → {fmtShortDate(c.last_date)}
                  </span>
                )}
                <span className="text-xs text-muted-foreground">
                  {shownSources.join(", ")}
                  {moreSources > 0 && ` +${moreSources}`}
                </span>
                <span
                  className={cn(
                    "rounded-[6px] px-2 py-0.5 text-2xs font-semibold uppercase",
                    c.confidence === "high" ? "bg-success/15 text-success-text" : c.confidence === "medium" ? "bg-warning/15 text-warning-text" : "bg-panel text-foreground",
                  )}
                >
                  {c.source_count} source{c.source_count !== 1 ? "s" : ""}
                </span>
                <span className="rounded-[6px] bg-panel px-2 py-0.5 text-2xs font-semibold text-foreground">{c.article_count} articles</span>
                {spike && <span className="rounded-[6px] bg-destructive/15 px-2 py-0.5 text-2xs font-semibold text-destructive-text">⚡ Active Spike</span>}
                {c.re_emerged && <span className="rounded-[6px] bg-primary/15 px-2 py-0.5 text-2xs font-semibold text-primary-text">↑ Re-emerging</span>}
              </button>
              {isOpen && (
                <div className="border-t border-border">
                  {c.articles.map((a) => (
                    <a key={a.id} href={a.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 border-b border-border px-4 py-2 text-xs outline-none last:border-b-0 hover:bg-surface focus-visible:ring-2 focus-visible:ring-ring">
                      <span className="flex-1 truncate text-foreground">{a.title}</span>
                      <span className="text-2xs text-muted-foreground">{a.source}</span>
                      <span className="text-2xs text-muted-foreground">{fmtShortDate(a.posted_on)}</span>
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
