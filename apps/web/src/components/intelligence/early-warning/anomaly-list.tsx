"use client";

import { useState } from "react";

import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { MeterBar } from "@/components/ui/meter-bar";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SelectableList } from "@/components/ui/selectable-list";
import { fmtShortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

import { byZ, CATEGORY_META, CATEGORY_ORDER, spikeName, type CategorizedSpike } from "./model";

type Mode = "grouped" | "all";

const MODES = [
  { value: "grouped", label: "Grouped" },
  { value: "all", label: "All by z" },
] as const;

interface AnomalyListProps {
  spikes: CategorizedSpike[];
  selected: string | null;
  onSelect: (value: string) => void;
}

/** Kartu Anomalies: baris = spike per hari (SelectableList, D5). Bar memakai max count PER grup supaya
 * skala tidak didominasi volume overall; mode "All by z" memakai grup yang sama agar bar baris tidak
 * berubah saat mode ditukar. */
export function AnomalyList({ spikes, selected, onSelect }: AnomalyListProps) {
  const [mode, setMode] = useState<Mode>("grouped");

  const maxByCat = new Map<string, number>();
  for (const s of spikes) maxByCat.set(s.category, Math.max(maxByCat.get(s.category) ?? 0, s.count));

  const renderItem = (s: CategorizedSpike) => {
    const high = s.severity === "high";
    return (
      <div className={cn("-mx-3 -my-2.5 rounded-[10px] px-3 py-2.5", high && "bg-destructive/5")}>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-foreground">{spikeName(s)}</p>
            <p className="text-xs text-muted-foreground">
              {CATEGORY_META[s.category].noun} · {fmtShortDate(s.date)}
            </p>
          </div>
          <Chip kind="severity" value={high ? "high" : "medium"}>
            {high ? "HIGH" : "MEDIUM"}
          </Chip>
          <span className={cn("w-16 text-right text-sm font-semibold tabular-nums", high ? "text-destructive-text" : "text-foreground")}>
            z {s.z_score}σ
          </span>
        </div>
        <MeterBar
          className="mt-2"
          variant="baseline"
          tone={high ? "destructive" : "primary"}
          value={s.count}
          max={maxByCat.get(s.category) ?? s.count}
          baseline={s.baseline_mean}
          aria-label={`${spikeName(s)}, ${s.count} articles on ${fmtShortDate(s.date)}`}
          label={`${s.count} articles that day · baseline ${s.baseline_mean}/day`}
        />
      </div>
    );
  };

  const list = (items: CategorizedSpike[], label: string) => (
    <SelectableList items={items} value={selected} onChange={onSelect} aria-label={label} renderItem={renderItem} />
  );

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5">
        <div>
          <h2 className="font-heading text-base font-semibold">Anomalies</h2>
          <p className="text-xs text-muted-foreground">Sorted by z-score within each group</p>
        </div>
        <SegmentedControl aria-label="Anomaly grouping" options={MODES} value={mode} onChange={setMode} />
      </div>
      <div className="flex flex-col gap-4 px-2">
        {mode === "all" ? (
          list([...spikes].sort(byZ), "Anomalies sorted by z-score")
        ) : (
          CATEGORY_ORDER.map((cat) => {
            const items = spikes.filter((s) => s.category === cat).sort(byZ);
            if (items.length === 0) return null;
            return (
              <section key={cat} className="flex flex-col gap-1">
                <h3 className="px-3 text-2xs font-bold tracking-[0.12em] text-muted-foreground uppercase">
                  {CATEGORY_META[cat].section} · {items.length}
                </h3>
                {list(items, CATEGORY_META[cat].section.toLowerCase())}
              </section>
            );
          })
        )}
      </div>
    </Card>
  );
}
