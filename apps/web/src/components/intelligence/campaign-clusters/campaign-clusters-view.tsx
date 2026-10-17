"use client";

import { useState } from "react";

import { TabPills } from "@/components/ui/tab-pills";
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
      <TabPills aria-label="Campaign views" className="mb-4" items={TABS} value={tab} onChange={setTab} />

      {tab === "campaigns" && <CampaignsPanel />}
      {tab === "clusters" && <SimpleClustersPanel />}
    </div>
  );
}
