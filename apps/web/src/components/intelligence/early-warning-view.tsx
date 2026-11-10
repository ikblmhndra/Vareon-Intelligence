"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { AnomalyList } from "@/components/intelligence/early-warning/anomaly-list";
import {
  byZ,
  categorize,
  CATEGORY_META,
  CATEGORY_ORDER,
  spikeName,
} from "@/components/intelligence/early-warning/model";
import { StrongestSignalPanel } from "@/components/intelligence/early-warning/strongest-signal-panel";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PresetControl } from "@/components/ui/preset-control";
import { StatePanel } from "@/components/ui/state-panel";
import { StatTile } from "@/components/ui/stat-tile";
import { api } from "@/lib/api/client";
import type { SpikesResponse } from "@/lib/api/loose-types";
import { fmtTime } from "@/lib/format";

const LOOKBACKS = [
  { value: 14, label: "14d" },
  { value: 30, label: "30d" },
  { value: 60, label: "60d" },
  { value: 90, label: "90d" },
] as const;

const Z_PRESETS = [
  { value: 1.5, label: "1.5σ" },
  { value: 2, label: "2σ" },
  { value: 2.5, label: "2.5σ" },
  { value: 3, label: "3σ" },
] as const;

// Teks langkah dari kode `services/spike.py` (C9): ubah bersama kodenya.
const STEPS = [
  "Count articles per day for each threat actor, industry, country and the overall volume over the lookback period.",
  "The baseline is every day before the last 7; days without articles count as 0.",
  "Skip any entity with fewer than 5 baseline days that have articles.",
  "z = (day count − baseline mean) / baseline deviation. Days in the last 7 with z at or above the threshold are anomalies.",
  "z of 3 or more is HIGH, otherwise MEDIUM. At most 20 anomalies per group.",
];

/** Early Warning (spec 2b 6.3): toolbar preset, empat tile, daftar anomali dan panel sinyal terkuat.
 * Port `loadSpikes()` (`intel.js:177-223`); sumber data tetap `GET /api/spikes`. */
export function EarlyWarningView() {
  const [lookbackDays, setLookbackDays] = useState(30);
  const [zThreshold, setZThreshold] = useState(2);
  // Pilihan baris disimpan sebagai kunci; bila hilang setelah parameter berubah, jatuh ke z tertinggi.
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

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
  const spikes = d ? categorize(d) : [];
  const strongest = [...spikes].sort(byZ)[0];
  const selected = spikes.find((s) => s.value === selectedKey) ?? strongest ?? null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          <PresetControl
            label="Lookback"
            aria-label="Lookback days"
            presets={LOOKBACKS}
            value={lookbackDays}
            onChange={setLookbackDays}
            min={14}
            max={90}
          />
          <PresetControl
            label="Z-score threshold"
            aria-label="Z-score threshold"
            presets={Z_PRESETS}
            value={zThreshold}
            onChange={setZThreshold}
            min={1.5}
            max={4}
            step={0.1}
          />
        </div>
        {d && (
          <p className="text-xs text-muted-foreground">
            {spikes.length} anomalies · recent window: last 7 days · updated {fmtTime(d.generated_at)}, refreshes every 15
            min
          </p>
        )}
      </div>

      {query.isPending && (
        <StatePanel variant="loading" title="Analyzing signals" description="Counting daily articles against each baseline." />
      )}
      {query.isError && (
        <StatePanel
          variant="error"
          title="Could not load early warning data"
          action={
            <Button variant="outline" size="sm" onClick={() => query.refetch()}>
              Retry
            </Button>
          }
        />
      )}

      {d && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {CATEGORY_ORDER.map((cat) => {
              const items = spikes.filter((s) => s.category === cat).sort(byZ);
              const high = items.filter((s) => s.severity === "high").length;
              const top = items[0];
              return (
                <StatTile
                  key={cat}
                  label={CATEGORY_META[cat].tile}
                  value={items.length}
                  tone={high > 0 ? "destructive" : "neutral"}
                  sub={
                    top ? (
                      <>
                        <span className="block truncate">
                          top: {spikeName(top)} · z {top.z_score}
                        </span>
                        <span className="block">
                          <span className={high > 0 ? "text-destructive-text" : undefined}>{high} high</span> ·{" "}
                          {items.length - high} medium
                        </span>
                      </>
                    ) : (
                      "no anomalies"
                    )
                  }
                />
              );
            })}
          </div>

          {spikes.length === 0 ? (
            <StatePanel
              variant="empty"
              title={`No anomalies above ${zThreshold}σ in the last ${lookbackDays} days`}
              description="Baseline activity looks normal. Lower the z-score threshold to surface weaker signals."
            />
          ) : (
            <div className="grid items-start gap-4 lg:grid-cols-[3fr_2fr]">
              <AnomalyList spikes={spikes} selected={selected?.value ?? null} onSelect={setSelectedKey} />
              <div className="flex flex-col gap-4">
                {selected && <StrongestSignalPanel spike={selected} data={d} />}
                <HowDetectionWorks />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function HowDetectionWorks() {
  return (
    <Card>
      <div className="flex flex-col gap-3 px-5">
        <h2 className="font-heading text-base font-semibold">How detection works</h2>
        <ol className="flex flex-col gap-2.5">
          {STEPS.map((text, i) => (
            <li key={i} className="flex gap-3 text-sm text-muted-foreground">
              <span
                aria-hidden="true"
                className="flex size-5 shrink-0 items-center justify-center rounded-full bg-surface text-2xs font-semibold text-foreground"
              >
                {i + 1}
              </span>
              <span>{text}</span>
            </li>
          ))}
        </ol>
      </div>
    </Card>
  );
}
