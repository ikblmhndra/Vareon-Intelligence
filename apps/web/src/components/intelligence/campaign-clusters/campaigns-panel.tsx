"use client";

import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { SeverityBadge, TrendArrow, VelocityBadge } from "@/components/intelligence/campaign-clusters/cluster-badges";
import { CampaignExpandedPanel } from "@/components/intelligence/campaign-clusters/campaign-expanded-panel";
import { GeopoliticalPanel } from "@/components/intelligence/campaign-clusters/geopolitical-panel";
import { ClusterPirDialog } from "@/components/intelligence/campaign-clusters/cluster-pir-dialog";
import { ArticleByIdDialog } from "@/components/intelligence/campaign-clusters/article-by-id-dialog";
import type { CampaignEntry, CampaignsResponse, CampaignTrend, MatchedPir } from "@/lib/api/loose-types";
import { tint } from "@/lib/tint";

type SortKey = "size" | "velocity" | "severity" | "first_seen" | "last_seen";
const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "size", label: "Article Count" },
  { key: "velocity", label: "Velocity" },
  { key: "severity", label: "Severity" },
  { key: "first_seen", label: "First Seen" },
  { key: "last_seen", label: "Last Seen" },
];

function sortCampaigns(campaigns: CampaignEntry[], sort: SortKey): CampaignEntry[] {
  const copy = [...campaigns];
  switch (sort) {
    case "velocity":
      return copy.sort((a, b) => b.velocity_articles_per_day - a.velocity_articles_per_day);
    case "severity":
      return copy.sort((a, b) => b.severity_score - a.severity_score);
    case "first_seen":
      return copy.sort((a, b) => a.first_seen.localeCompare(b.first_seen));
    case "last_seen":
      return copy.sort((a, b) => b.last_seen.localeCompare(a.last_seen));
    case "size":
    default:
      return copy.sort((a, b) => b.size - a.size);
  }
}

function huntPack(c: CampaignEntry) {
  const pack = {
    cluster_id: c.cluster_id,
    cluster_name: c.summary_title || c.cluster_id,
    generated_at: new Date().toISOString(),
    date_range: { first_seen: c.first_seen, last_seen: c.last_seen },
    article_count: c.size,
    dominant_tas: c.dominant_tas,
    dominant_industries: c.dominant_industries,
    dominant_countries: c.dominant_countries,
    attack_techniques: c.attack_techniques,
    cve_ids: c.cve_ids,
    iocs: c.iocs.map((i) => ({ type: i.type, value: i.value })),
    matched_pirs: c.matched_pirs,
  };
  const blob = new Blob([JSON.stringify(pack, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `hunt-pack-${c.cluster_id}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

/** Port sub-view "Campaigns" Pipeline 2 (`clusters.js:114-261`) --
 * auto-load (beda dari Clusters Pipeline 1 yang manual-generate),
 * enrichment kaya per-campaign. */
export function CampaignsPanel() {
  const [days, setDays] = useState(7);
  const [minSize, setMinSize] = useState(3);
  const [sort, setSort] = useState<SortKey>("size");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [pirTarget, setPirTarget] = useState<MatchedPir | null>(null);
  const [articleTarget, setArticleTarget] = useState<number | null>(null);
  const rowRefs = useRef<Record<string, HTMLTableRowElement | null>>({});

  const query = useQuery({
    queryKey: ["campaign-clusters", "campaigns", days, minSize],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/clusters/recent", { params: { query: { days, min_size: minSize } } });
      if (error) throw error;
      return data as unknown as CampaignsResponse;
    },
  });

  function toggleExpand(clusterId: string) {
    setExpanded((e) => ({ ...e, [clusterId]: !e[clusterId] }));
  }

  function jumpToCampaign(clusterId: string) {
    setExpanded((e) => ({ ...e, [clusterId]: true }));
    requestAnimationFrame(() => {
      rowRefs.current[clusterId]?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  const campaigns = sortCampaigns(query.data?.campaigns ?? [], sort);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-2 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Days</Label>
          <Input type="number" aria-label="Days" min={1} max={90} value={days} onChange={(e) => setDays(Number(e.target.value) || 7)} className="w-20 font-mono text-xs" />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Min Size</Label>
          <Input type="number" aria-label="Min size" min={2} max={50} value={minSize} onChange={(e) => setMinSize(Number(e.target.value) || 3)} className="w-20 font-mono text-xs" />
        </div>
        <span className="ml-auto font-mono text-[13px] text-muted-foreground">
          {campaigns.length} campaign cluster{campaigns.length !== 1 ? "s" : ""} found
        </span>
      </div>

      <GeopoliticalPanel days={days} />

      {query.isPending && <p className="py-10 text-center text-xs text-muted-foreground">Clustering campaigns…</p>}
      {query.isError && <p className="py-10 text-center text-xs text-destructive">Error loading campaigns.</p>}
      {query.data && campaigns.length === 0 && <p className="py-10 text-center text-xs text-muted-foreground">No campaign clusters found for selected parameters.</p>}

      {campaigns.length > 0 && (
        <>
          <div className="mb-2 flex flex-wrap items-center gap-1.5 border-b border-border pb-2 font-mono text-xs text-muted-foreground">
            Sort:
            {SORT_OPTIONS.map((o) => (
              <button
                key={o.key}
                type="button"
                onClick={() => setSort(o.key)}
                className={cn("rounded-md border px-2 py-1", sort === o.key ? "border-primary/50 bg-primary/15 text-primary-text" : "border-border text-muted-foreground")}
              >
                {o.label}
              </button>
            ))}
          </div>

          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-border text-left text-muted-foreground">
                <th className="px-2 py-1.5">Summary Title</th>
                <th className="w-20 px-2 py-1.5 text-center">Size / Velocity</th>
                <th className="w-20 px-2 py-1.5 text-left">Severity</th>
                <th className="w-24 px-2 py-1.5 text-left">First Seen</th>
                <th className="w-24 px-2 py-1.5 text-left">Last Seen</th>
                <th className="px-2 py-1.5 text-left">TAs</th>
                <th className="px-2 py-1.5 text-left">Industries</th>
                <th className="px-2 py-1.5 text-left">Countries</th>
                <th className="px-2 py-1.5 text-left">ATT&amp;CK</th>
                <th className="px-2 py-1.5 text-left">Actions</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => {
                const isOpen = Boolean(expanded[c.cluster_id]);
                return (
                  <CampaignRow
                    key={c.cluster_id}
                    campaign={c}
                    isOpen={isOpen}
                    rowRef={(el) => {
                      rowRefs.current[c.cluster_id] = el;
                    }}
                    onToggle={() => toggleExpand(c.cluster_id)}
                    onHuntPack={() => huntPack(c)}
                    onOpenArticle={setArticleTarget}
                    onOpenPir={setPirTarget}
                    onJumpToCampaign={jumpToCampaign}
                  />
                );
              })}
            </tbody>
          </table>
        </>
      )}

      <ClusterPirDialog pir={pirTarget} onClose={() => setPirTarget(null)} />
      <ArticleByIdDialog articleId={articleTarget} onClose={() => setArticleTarget(null)} />
    </div>
  );
}

function CampaignRow({
  campaign: c,
  isOpen,
  rowRef,
  onToggle,
  onHuntPack,
  onOpenArticle,
  onOpenPir,
  onJumpToCampaign,
}: {
  campaign: CampaignEntry;
  isOpen: boolean;
  rowRef: (el: HTMLTableRowElement | null) => void;
  onToggle: () => void;
  onHuntPack: () => void;
  onOpenArticle: (articleId: number) => void;
  onOpenPir: (pir: MatchedPir) => void;
  onJumpToCampaign: (clusterId: string) => void;
}) {
  const trendQuery = useQuery({
    queryKey: ["campaign-clusters", "trend", c.cluster_id],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/clusters/{cluster_id}/trends", { params: { path: { cluster_id: c.cluster_id } } });
      if (error) throw error;
      return data as unknown as CampaignTrend;
    },
    enabled: isOpen,
  });

  return (
    <>
      <tr ref={rowRef} className={cn("border-b border-border", c.velocity_alert && "bg-destructive/5")}>
        <td className="max-w-[260px] cursor-pointer px-2 py-1.5" onClick={onToggle}>
          <span className="mr-1 text-muted-foreground">{isOpen ? "▼" : "▶"}</span>
          <span className="text-foreground">{c.summary_title || c.cluster_id}</span>
          {trendQuery.data && <TrendArrow direction={trendQuery.data.trend_direction} growthRate={trendQuery.data.growth_rate} />}
          <SeverityBadge label={c.severity_label} score={c.severity_score} />
          {c.matched_pirs.length > 0 && <span className="ml-1 rounded-full border border-destructive/30 bg-destructive/10 px-1.5 py-0.5 font-mono text-xs text-destructive-text">PIR</span>}
        </td>
        <td className="px-2 py-1.5 text-center whitespace-nowrap text-foreground">
          {c.size}
          <VelocityBadge label={c.velocity_label} articlesPerDay={c.velocity_articles_per_day} />
          {c.new_iocs_24h > 0 && <span className="ml-1 rounded-full border border-success/35 bg-success/12 px-1.5 py-0.5 font-mono text-xs text-success-text">NEW: {c.new_iocs_24h} IOCs</span>}
        </td>
        <td className="px-2 py-1.5">
          <SeverityBadge label={c.severity_label} score={c.severity_score} />
        </td>
        <td className="px-2 py-1.5 font-mono text-xs text-muted-foreground">{c.first_seen}</td>
        <td className="px-2 py-1.5 font-mono text-xs text-muted-foreground">{c.last_seen}</td>
        <td className="max-w-[160px] px-2 py-1.5">
          <ChipList items={c.dominant_tas} color="var(--severity-high)" />
        </td>
        <td className="max-w-[160px] px-2 py-1.5">
          <ChipList items={c.dominant_industries} color="var(--info)" />
        </td>
        <td className="max-w-[120px] px-2 py-1.5">
          <ChipList items={c.dominant_countries} color="var(--info)" />
        </td>
        <td className="max-w-[200px] px-2 py-1.5">
          <div className="flex flex-wrap items-center gap-1">
            <ChipList items={c.attack_techniques.slice(0, 5)} color="var(--tag-violet)" />
            {c.kill_chain.completeness_label && <span className="font-mono text-xs text-muted-foreground">{c.kill_chain.completeness_score}%</span>}
          </div>
        </td>
        <td className="px-2 py-1.5">
          <button type="button" onClick={onHuntPack} className="rounded-full border border-primary/30 bg-primary/8 px-2 py-1 font-mono text-xs text-primary-text">
            Hunt Pack
          </button>
        </td>
      </tr>
      {isOpen && (
        <tr>
          <td colSpan={10} className="p-0">
            <CampaignExpandedPanel campaign={c} onOpenArticle={onOpenArticle} onOpenPir={onOpenPir} onJumpToCampaign={onJumpToCampaign} />
          </td>
        </tr>
      )}
    </>
  );
}

function ChipList({ items, color }: { items: string[]; color: string }) {
  if (items.length === 0) return <span className="font-mono text-xs text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((v) => (
        <span key={v} className="rounded-full border px-1.5 py-0.5 font-mono text-xs" style={{ background: tint(color, 9), borderColor: tint(color, 27), color }}>
          {v}
        </span>
      ))}
    </div>
  );
}
