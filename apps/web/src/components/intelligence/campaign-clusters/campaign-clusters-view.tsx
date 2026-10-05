"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import { SimpleClustersPanel } from "@/components/intelligence/campaign-clusters/simple-clusters-panel";
import { CampaignsPanel } from "@/components/intelligence/campaign-clusters/campaigns-panel";

const TABS = [
  { value: "campaigns", label: "Campaigns" },
  { value: "clusters", label: "Clusters (Simple)" },
] as const;
type Tab = (typeof TABS)[number]["value"];

/** Port sub-view `campaigns`+`clusters` (`intel.js:5-30`) -- dua
 * pipeline TF-IDF independen (lihat docstring `cti_api.services.
 * cluster`/`campaign`): Campaigns (Pipeline 2, union-find, enrichment
 * kaya, AUTO-LOAD) jadi tab default -- lebih sering dipakai analis,
 * sama urutan prioritas legacy (`campaigns` listed dulu dari
 * `intelSwitchViewAndLoad`'s auto-dispatch). Clusters (Pipeline 1,
 * greedy, manual-generate) tab kedua. */
export function CampaignClustersView() {
  const [tab, setTab] = useState<Tab>("campaigns");

  return (
    <div>
      <div className="mb-4 flex gap-1.5 overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            onClick={() => setTab(t.value)}
            className={cn(
              "shrink-0 whitespace-nowrap rounded-full border px-4 py-2 text-sm font-medium transition-colors duration-200",
              tab === t.value ? "border-primary/30 bg-primary/10 text-primary" : "border-border bg-surface text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "campaigns" && <CampaignsPanel />}
      {tab === "clusters" && <SimpleClustersPanel />}
    </div>
  );
}
