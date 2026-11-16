"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { CampaignsPanel, useCampaigns } from "@/components/intelligence/campaign-clusters/campaigns-panel";
import { SimpleClustersPanel } from "@/components/intelligence/campaign-clusters/simple-clusters-panel";
import { TabPills } from "@/components/ui/tab-pills";

type View = "campaigns" | "simple";
const DEFAULT_DAYS = 7;

// `useSearchParams` di client component wajib dibungkus Suspense (Next 16).
export function CampaignClustersView() {
  return (
    <Suspense fallback={null}>
      <View />
    </Suspense>
  );
}

/** Dua pipeline TF-IDF independen (lihat docstring `cti_api.services.cluster`/`campaign`): Campaigns
 * (Pipeline 2, union-find, enrichment kaya, auto-load) = tampilan baku, Clusters (Simple, Pipeline 1,
 * greedy) = `?view=simple`. URL memegang tampilan (`?view=`) dan campaign terpilih (`?id=`, dipakai tautan
 * dari halaman PIR); DAYS/MIN SIZE lokal. Query campaign dipegang di sini agar jumlahnya muncul di pil tab. */
function View() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const view: View = params.get("view") === "simple" ? "simple" : "campaigns";
  // `?days=` (1-90) = DAYS awal; tautan dari halaman PIR membawa 30 karena PIR mencocokkan campaign 30 hari.
  const daysParam = Number(params.get("days"));
  const [days, setDays] = useState(Number.isInteger(daysParam) && daysParam >= 1 && daysParam <= 90 ? daysParam : DEFAULT_DAYS);
  const [minSize, setMinSize] = useState(3);
  const campaigns = useCampaigns(days, minSize);

  function setUrl(next: { view?: View; id?: string | null; days?: number }) {
    const qs = new URLSearchParams(params.toString());
    if (next.view !== undefined) {
      if (next.view === "campaigns") qs.delete("view");
      else qs.set("view", next.view);
    }
    if (next.id !== undefined) {
      if (next.id == null) qs.delete("id");
      else qs.set("id", next.id);
    }
    if (next.days !== undefined) {
      if (next.days === DEFAULT_DAYS) qs.delete("days");
      else qs.set("days", String(next.days));
    }
    const s = qs.toString();
    router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false });
  }

  const tabs = (
    <TabPills
      aria-label="Campaign views"
      items={[
        { value: "campaigns" as const, label: "Campaigns", count: campaigns.data?.total },
        { value: "simple" as const, label: "Clusters (Simple)" },
      ]}
      value={view}
      onChange={(v) => setUrl({ view: v })}
    />
  );

  if (view === "simple") return <SimpleClustersPanel tabs={tabs} />;
  return (
    <CampaignsPanel
      tabs={tabs}
      query={campaigns}
      days={days}
      onDaysChange={(d) => {
        setDays(d);
        setUrl({ days: d });
      }}
      minSize={minSize}
      onMinSizeChange={setMinSize}
      selectedId={params.get("id")}
      onSelect={(id) => setUrl({ id })}
    />
  );
}
