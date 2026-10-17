"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { SpikeEntry, SpikesResponse } from "@/lib/api/loose-types";

interface CategorizedSpike extends SpikeEntry {
  category: string;
}

/** Port `loadSpikes()` (`intel.js:177-223`) -- gabung 4 kategori
 * (`overall`→"Overall Volume", `threat_actors`, `countries`,
 * `industries`), urut z-score desc, dikelompokin per kategori. */
export function EarlyWarningView() {
  const [lookbackDays, setLookbackDays] = useState(30);
  const [zThreshold, setZThreshold] = useState(2.0);

  const query = useQuery({
    queryKey: ["intelligence", "spikes", lookbackDays, zThreshold],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/spikes", {
        params: { query: { lookback_days: lookbackDays, z_threshold: zThreshold } },
      });
      if (error) throw error;
      return data as unknown as SpikesResponse;
    },
  });

  const d = query.data;
  const allSpikes: CategorizedSpike[] = d
    ? [
        ...d.overall.map((s) => ({ ...s, category: "Overall Volume" })),
        ...d.threat_actors.map((s) => ({ ...s, category: "Threat Actor" })),
        ...d.countries.map((s) => ({ ...s, category: "Country" })),
        ...d.industries.map((s) => ({ ...s, category: "Industry" })),
      ].sort((a, b) => b.z_score - a.z_score)
    : [];

  const sections = new Map<string, CategorizedSpike[]>();
  for (const s of allSpikes) {
    const arr = sections.get(s.category) ?? [];
    arr.push(s);
    sections.set(s.category, arr);
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Lookback days</Label>
          <Input
            type="number" aria-label="Lookback days"
            min={14}
            max={90}
            value={lookbackDays}
            onChange={(e) => setLookbackDays(Number(e.target.value) || 30)}
            className="w-24 font-mono text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Z-score threshold</Label>
          <Input
            type="number" aria-label="Z-score threshold"
            min={1.5}
            max={4}
            step={0.1}
            value={zThreshold}
            onChange={(e) => setZThreshold(Number(e.target.value) || 2.0)}
            className="w-24 font-mono text-xs"
          />
        </div>
        <span className="mb-1.5 font-mono text-xs text-muted-foreground">{allSpikes.length} anomalies</span>
      </div>

      {query.isPending && <p className="py-8 text-center font-mono text-xs text-muted-foreground">Analyzing signals…</p>}
      {query.isError && <p className="py-8 text-center text-xs text-destructive">Failed to load early warning data.</p>}

      {d && allSpikes.length === 0 && (
        <p className="py-8 text-center font-mono text-xs text-muted-foreground">
          No anomalies detected in the selected window — baseline activity appears normal
        </p>
      )}

      {[...sections.entries()].map(([cat, spikes]) => (
        <div key={cat} className="mb-4">
          <div className="mb-1.5 text-sm font-semibold text-muted-foreground">{cat} Spikes</div>
          <div className="space-y-1.5">
            {spikes.map((s, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2.5 rounded-xl border border-border bg-background px-3 py-1.5">
                <span className="min-w-[100px] font-mono text-xs text-foreground">{s.entity || "Overall"}</span>
                <span className="font-mono text-xs text-muted-foreground">date: {s.date}</span>
                <span className="font-mono text-xs text-muted-foreground">
                  count: <strong className="text-foreground">{s.count}</strong>
                </span>
                <span className="font-mono text-xs text-muted-foreground">baseline: {s.baseline_mean}/day</span>
                <Badge variant={s.severity === "high" ? "destructive" : "outline"} className="text-xs">
                  {s.severity.toUpperCase()}
                </Badge>
                <span className={cn("font-mono text-xs", s.severity === "high" ? "text-destructive" : "text-primary")}>
                  z={s.z_score}σ
                </span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
