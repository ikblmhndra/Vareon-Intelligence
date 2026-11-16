"use client";

import { useState, type ReactNode } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { FilterSelect } from "@/components/ui/filter-select";
import { MasterDetail } from "@/components/ui/master-detail";
import { PresetControl } from "@/components/ui/preset-control";
import { SelectableList } from "@/components/ui/selectable-list";
import { Notice } from "@/components/ui/notice";
import { StatePanel } from "@/components/ui/state-panel";
import { TrendArrow } from "@/components/intelligence/campaign-clusters/cluster-badges";
import { CampaignDetailCard } from "@/components/intelligence/campaign-clusters/campaign-detail-card";
import { ClusterPirDialog } from "@/components/intelligence/campaign-clusters/cluster-pir-dialog";
import { ArticleByIdDialog } from "@/components/intelligence/campaign-clusters/article-by-id-dialog";
import type { CampaignEntry, CampaignsResponse, CampaignTrend, MatchedPir } from "@/lib/api/loose-types";

type SortKey = "severity" | "size" | "velocity" | "last_seen";
const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "severity", label: "severity" },
  { value: "size", label: "size" },
  { value: "velocity", label: "velocity" },
  { value: "last_seen", label: "last seen" },
];
const SORT_PHRASE: Record<SortKey, string> = {
  severity: "severity score",
  size: "article count",
  velocity: "velocity",
  last_seen: "last seen",
};

export const DAYS_PRESETS = [
  { value: 7, label: "7d" },
  { value: 30, label: "30d" },
  { value: 90, label: "90d" },
];
const MIN_SIZE_PRESETS = [
  { value: 2, label: "2" },
  { value: 3, label: "3" },
  { value: 5, label: "5" },
  { value: 10, label: "10" },
];

export function sortCampaigns(campaigns: CampaignEntry[], sort: SortKey): CampaignEntry[] {
  const copy = [...campaigns];
  switch (sort) {
    case "velocity":
      return copy.sort((a, b) => b.velocity_articles_per_day - a.velocity_articles_per_day);
    case "severity":
      return copy.sort((a, b) => b.severity_score - a.severity_score);
    case "last_seen":
      return copy.sort((a, b) => b.last_seen.localeCompare(a.last_seen));
    case "size":
    default:
      return copy.sort((a, b) => b.size - a.size);
  }
}

/** Query campaign (Pipeline 2, auto-load). Dipanggil `CampaignClustersView` supaya jumlah di pil tab
 * "Campaigns" tetap tersedia saat tab Clusters (Simple) aktif dan hasilnya ter-cache antar-tab. */
export function useCampaigns(days: number, minSize: number) {
  return useQuery({
    queryKey: ["campaign-clusters", "campaigns", days, minSize],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/clusters/recent", { params: { query: { days, min_size: minSize } } });
      if (error) throw error;
      return data as unknown as CampaignsResponse;
    },
  });
}

const VELOCITY_TEXT: Record<CampaignEntry["velocity_label"], string> = {
  surging: "text-destructive-text",
  active: "text-warning-text",
  moderate: "text-foreground",
  slow: "text-muted-foreground",
};
const VELOCITY_DOT: Record<CampaignEntry["velocity_label"], string> = {
  surging: "bg-destructive",
  active: "bg-warning",
  moderate: "bg-foreground",
  slow: "bg-muted-foreground",
};

/** Panah tren per kartu: query `/trends` (baca DB murah) berbagi cache dengan bagian Trend di detail. */
function CardTrend({ clusterId }: { clusterId: string }) {
  const query = useQuery({
    queryKey: ["campaign-clusters", "trend", clusterId],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/clusters/{cluster_id}/trends", { params: { path: { cluster_id: clusterId } } });
      // 404 = cluster belum tersimpan: bukan error, jangan diulang-ulang (dulu ~8 request per kartu).
      if (response.status === 404) return null;
      if (error) throw error;
      return data as unknown as CampaignTrend;
    },
    staleTime: 5 * 60_000,
    retry: false,
  });
  if (!query.data) return null;
  return <TrendArrow direction={query.data.trend_direction} growthRate={query.data.growth_rate} />;
}

const tag = "rounded-[6px] bg-panel px-2 py-0.5 text-2xs font-semibold text-foreground";

/** Isi kartu campaign. Kartu adalah tombol option, jadi hanya teks/chip polos (tanpa tautan entity). */
function CampaignCardBody({ c }: { c: CampaignEntry }) {
  const actors = c.dominant_tas.slice(0, 2);
  const extraActors = c.dominant_tas.length - actors.length;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Chip kind="severity" value={c.severity_label}>
          {`${c.severity_label.toUpperCase()} ${c.severity_score}`}
        </Chip>
        {c.velocity_alert && <Chip kind="status" value="open">VELOCITY ALERT</Chip>}
        {c.new_iocs_24h > 0 && (
          <Chip kind="status" value="completed" className="normal-case">
            {`NEW ${c.new_iocs_24h} IOCs`}
          </Chip>
        )}
        <CardTrend clusterId={c.cluster_id} />
        <span className="ml-auto text-xs text-muted-foreground">
          {c.size} articles · {c.days_active} days active
        </span>
      </div>
      <p className="font-heading text-base font-semibold text-foreground">{c.summary_title || c.cluster_id}</p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {actors.map((a) => (
          <span key={a} className={tag}>
            {a}
          </span>
        ))}
        {extraActors > 0 && <span>+{extraActors}</span>}
        {c.dominant_industries.length > 0 && <span>{c.dominant_industries.slice(0, 3).join(" · ")}</span>}
        {c.dominant_countries.length > 0 && <span>{c.dominant_countries.slice(0, 4).join(" · ")}</span>}
        <span className={cn("inline-flex items-center gap-1.5 font-semibold", VELOCITY_TEXT[c.velocity_label])}>
          <span aria-hidden="true" className={cn("size-1.5 rounded-full", VELOCITY_DOT[c.velocity_label])} />
          {c.velocity_label} · {c.velocity_articles_per_day.toFixed(1)}/day
        </span>
      </div>
    </div>
  );
}

interface CampaignsPanelProps {
  /** Pil tab (Campaigns | Clusters (Simple)) dari view; dirender di baris pertama toolbar. */
  tabs: ReactNode;
  query: UseQueryResult<CampaignsResponse>;
  days: number;
  onDaysChange: (v: number) => void;
  minSize: number;
  onMinSizeChange: (v: number) => void;
  selectedId: string | null;
  onSelect: (clusterId: string) => void;
}

/** Campaigns (spec 2b 6.10, port Pipeline 2 `clusters.js:114-261`): toolbar, daftar kartu urut, dan panel
 * detail. Campaign terpilih = `?id=` bila ada di daftar, selain itu kartu pertama. */
export function CampaignsPanel({ tabs, query, days, onDaysChange, minSize, onMinSizeChange, selectedId, onSelect }: CampaignsPanelProps) {
  const [sort, setSort] = useState<SortKey>("severity");
  const [pirTarget, setPirTarget] = useState<MatchedPir | null>(null);
  const [articleTarget, setArticleTarget] = useState<number | null>(null);

  const campaigns = sortCampaigns(query.data?.campaigns ?? [], sort);
  const requested = campaigns.find((c) => c.cluster_id === selectedId);
  const selected = requested ?? campaigns[0] ?? null;
  // `?id=` yang tak ada di jendela ini (mis. DAYS lebih sempit dari tautan asal): jangan pindah diam-diam.
  const missing = selectedId != null && query.data !== undefined && !requested && selected !== null;

  let list: ReactNode;
  if (query.isPending) list = <StatePanel variant="loading" title="Clustering campaigns" description="This may take a few seconds." />;
  else if (query.isError)
    list = (
      <StatePanel
        variant="error"
        title="Failed to load campaigns"
        action={
          <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
            Retry
          </Button>
        }
      />
    );
  else if (campaigns.length === 0)
    list = <StatePanel variant="empty" title="No campaign clusters found" description="Try a longer period or a smaller minimum size." />;
  else
    list = (
      <SelectableList
        variant="card"
        aria-label="Campaigns"
        items={campaigns.map((c) => ({ value: c.cluster_id, c }))}
        value={selected?.cluster_id ?? null}
        onChange={onSelect}
        renderItem={({ c }) => <CampaignCardBody c={c} />}
      />
    );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        {tabs}
        <PresetControl label="Days" aria-label="Days" presets={DAYS_PRESETS} value={days} onChange={onDaysChange} min={1} max={90} />
        <PresetControl label="Min size (articles)" aria-label="Minimum campaign size" presets={MIN_SIZE_PRESETS} value={minSize} onChange={onMinSizeChange} min={2} max={50} />
        {query.data && (
          <span className="ml-auto text-xs text-muted-foreground">
            {query.data.total} campaigns · {query.data.campaign_links.length} links between them
          </span>
        )}
      </div>

      <MasterDetail
        list={
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="font-heading text-lg font-semibold">Campaigns</h2>
                <p className="text-xs text-muted-foreground">Sorted by {SORT_PHRASE[sort]}</p>
              </div>
              <FilterSelect prefix="Sort" value={sort} onChange={setSort} options={SORT_OPTIONS} />
            </div>
            {list}
          </div>
        }
        detail={
          selected ? (
            <div className="flex flex-col gap-3 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
              {missing && <Notice tone="info" title="This campaign is not in the selected window. Widen DAYS to find it." />}
              <CampaignDetailCard
                key={selected.cluster_id}
                campaign={selected}
                // Endpoint geopolitical menolak days < 7 (422); Custom 1-6 hari memakai 7.
                days={Math.max(7, days)}
                onOpenArticle={setArticleTarget}
                onOpenPir={setPirTarget}
                onSelectCampaign={onSelect}
              />
            </div>
          ) : (
            query.data && <StatePanel variant="empty" title="Select a campaign to see its detail" />
          )
        }
      />

      <ClusterPirDialog pir={pirTarget} onClose={() => setPirTarget(null)} />
      <ArticleByIdDialog articleId={articleTarget} onClose={() => setArticleTarget(null)} />
    </div>
  );
}
