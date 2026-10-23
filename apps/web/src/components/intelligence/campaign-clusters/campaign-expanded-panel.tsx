"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { MindmapWidget } from "@/components/mindmap/mindmap-widget";
import { DiamondModelView } from "@/components/intelligence/campaign-clusters/diamond-model-view";
import { KillChainView } from "@/components/intelligence/campaign-clusters/kill-chain-view";
import { CvePriorityChip, LinkTypeBadge } from "@/components/intelligence/campaign-clusters/cluster-badges";
import type { CampaignEntry, CampaignTrend, MatchedPir } from "@/lib/api/loose-types";

const TREND_COLOR: Record<string, string> = { growing: "var(--severity-critical)", declining: "var(--success)", dormant: "var(--muted-foreground)", stable: "var(--severity-medium)" };

function TrendSparkline({ timeline, width, height }: { timeline: { date: string; count: number }[]; width: number; height: number }) {
  if (timeline.length < 2) return null;
  const counts = timeline.map((p) => p.count);
  const max = Math.max(...counts, 1);
  const min = Math.min(...counts);
  const range = max - min || 1;
  const step = width / (counts.length - 1);
  const points = counts.map((v, i) => `${(i * step).toFixed(1)},${(height - ((v - min) / range) * height).toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      <polyline points={points} fill="none" stroke="var(--primary)" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" opacity={0.7} />
    </svg>
  );
}

function CampaignTrendSection({ clusterId }: { clusterId: string }) {
  const query = useQuery({
    queryKey: ["campaign-clusters", "trend", clusterId],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/clusters/{cluster_id}/trends", { params: { path: { cluster_id: clusterId } } });
      if (error) throw error;
      return data as unknown as CampaignTrend;
    },
  });

  const trend = query.data;
  if (!trend || !trend.timeline || trend.timeline.length < 2) return null;
  const color = TREND_COLOR[trend.trend_direction] ?? TREND_COLOR.stable;
  const gr = trend.growth_rate != null ? `${trend.growth_rate > 0 ? "+" : ""}${trend.growth_rate}%` : "—";

  return (
    <div className="mb-2.5">
      <div className="mb-1.5 flex flex-wrap items-center gap-2 text-sm font-semibold text-muted-foreground">
        Campaign Trend
        <span className="rounded-full border border-border bg-surface px-1.5 py-0.5 text-xs normal-case" style={{ color }}>
          {trend.trend_direction}
        </span>
        <span className="text-xs normal-case" style={{ color }}>
          {gr} 7d
        </span>
        {trend.predicted_peak && <span className="text-xs text-muted-foreground normal-case">est. peak {trend.predicted_peak}</span>}
      </div>
      <div className="flex items-center gap-2.5 rounded-xl border border-border bg-background px-2.5 py-1.5">
        <TrendSparkline timeline={trend.timeline} width={200} height={32} />
        <span className="font-mono text-xs text-muted-foreground">
          {trend.timeline[0]?.date} → {trend.timeline[trend.timeline.length - 1]?.date}
        </span>
      </div>
    </div>
  );
}

/** Port `_renderCampaignExpanded()` (`clusters.js:263-427`) -- isi row
 * expand: trend, severity breakdown, kill chain, diamond model,
 * matched PIRs, member articles, IOCs, prioritized CVEs, mind map
 * (consumer KEDUA `MindmapWidget` G5, setelah Threat Actor Room G6),
 * related campaigns.
 *
 * CVE chip klik: legacy manggil `openCveDetail()` (cross-tab, SPA
 * satu-halaman lama bisa buka modal CVE Tracker dari tab Intelligence
 * manapun). Di sini `/cve` sub-route TERPISAH (keputusan arsitektur
 * Fase 8), gak ada state cross-page buat "buka modal CVE tab lain" --
 * diganti buka NVD langsung (deviasi disengaja, dicatat, bukan port
 * apa adanya karena arsitekturnya beda struktural). */
export function CampaignExpandedPanel({
  campaign: c,
  onOpenArticle,
  onOpenPir,
  onJumpToCampaign,
}: {
  campaign: CampaignEntry;
  onOpenArticle: (articleId: number) => void;
  onOpenPir: (pir: MatchedPir) => void;
  onJumpToCampaign: (clusterId: string) => void;
}) {
  const bd = c.severity_breakdown;
  const cvePrioList = c.prioritized_cves.length > 0 ? c.prioritized_cves : c.cve_ids.map((id) => ({ cve_id: id, priority_score: 0, priority_label: null, patch_urgency: null, cvss_score: null, in_tech_stack: false, severity: null, cisa_kev: false, poc_available: false, actively_exploited: false }));

  return (
    <div className="border-t border-border bg-background/40 p-4">
      <CampaignTrendSection clusterId={c.cluster_id} />

      <div className="mb-2.5">
        <div className="mb-1.5 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
          Severity Breakdown
          <span className="rounded-full border px-1.5 py-0.5 text-xs font-bold normal-case border-border">{c.severity_label.toUpperCase()} {c.severity_score}</span>
        </div>
        <div className="rounded-xl border border-border bg-background p-2.5">
          {(
            [
              ["TA Sophistication", bd.ta_sophistication, bd.raw.ta_sophistication, "30%"],
              ["IOC Confidence", bd.ioc_confidence, bd.raw.ioc_confidence, "20%"],
              ["CVE Criticality", bd.cve_criticality, bd.raw.cve_criticality, "20%"],
              ["Campaign Velocity", bd.campaign_velocity, bd.raw.campaign_velocity, "15%"],
              ["Source Quality", bd.source_quality, bd.raw.source_quality, "15%"],
            ] as [string, number, number, string][]
          ).map(([name, contrib, raw, weight]) => (
            <div key={name} className="flex items-center gap-2 py-0.5 font-mono text-xs">
              <span className="w-[130px] flex-shrink-0 text-muted-foreground">
                {name} ({weight})
              </span>
              <div className="h-1 flex-1 rounded-full bg-foreground/10">
                <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round(raw)}%` }} />
              </div>
              <span className="w-8 text-right text-foreground">{raw}</span>
              <span className="w-9 text-right text-muted-foreground">+{contrib}</span>
            </div>
          ))}
        </div>
      </div>

      <KillChainView killChain={c.kill_chain} />
      <DiamondModelView clusterName={c.cluster_name} model={c.diamond_model} />

      {c.matched_pirs.length > 0 && (
        <div className="mb-2.5">
          <div className="mb-1.5 text-sm font-semibold text-muted-foreground">Matched PIRs ({c.matched_pirs.length})</div>
          <div className="overflow-hidden rounded-md border border-border">
            {c.matched_pirs.map((pir) => (
              <button key={pir.id} type="button" onClick={() => onOpenPir(pir)} className="flex w-full items-center gap-2 border-b border-border px-3 py-1.5 text-left last:border-b-0 hover:bg-accent">
                <span className="flex-shrink-0 rounded-full border border-destructive/30 bg-destructive/10 px-1.5 py-0.5 font-mono text-xs text-destructive-text">PIR</span>
                <span className="text-xs text-foreground">{pir.title}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="mb-2.5">
        <div className="mb-1.5 text-sm font-semibold text-muted-foreground">Member Articles ({c.member_article_ids.length})</div>
        <div className="max-h-[180px] overflow-y-auto rounded-md border border-border">
          {c.member_article_ids.length === 0 ? (
            <div className="p-2 font-mono text-xs text-muted-foreground">None</div>
          ) : (
            c.member_article_ids.map((aid, i) => (
              <button key={aid} type="button" onClick={() => onOpenArticle(aid)} className="block w-full border-b border-border px-3 py-1.5 text-left text-xs text-primary last:border-b-0 hover:bg-accent">
                {c.titles[i] || aid}
              </button>
            ))
          )}
        </div>
      </div>

      {c.iocs.length > 0 && (
        <div className="mb-2.5">
          <div className="mb-1.5 text-sm font-semibold text-muted-foreground">IOCs ({c.iocs.length})</div>
          <div className="flex flex-wrap gap-1">
            {c.iocs.slice(0, 20).map((ioc, i) => (
              <span key={i} title={ioc.type} className="rounded-full border border-destructive/25 bg-destructive/8 px-1.5 py-0.5 font-code text-xs text-destructive-text">
                {ioc.value}
              </span>
            ))}
          </div>
        </div>
      )}

      {cvePrioList.length > 0 && (
        <div className="mb-2.5">
          <div className="mb-1.5 text-sm font-semibold text-muted-foreground">CVEs ({cvePrioList.length})</div>
          <div className="flex flex-wrap gap-1">
            {cvePrioList.slice(0, 20).map((cve) => (
              <CvePriorityChip
                key={cve.cve_id}
                cve={cve}
                onClick={() => window.open(`https://nvd.nist.gov/vuln/detail/${cve.cve_id}`, "_blank", "noopener,noreferrer")}
              />
            ))}
          </div>
        </div>
      )}

      <MindmapWidget featureType="cluster" docId={c.cluster_id} title={c.cluster_name} />

      {c.related_campaigns.length > 0 && (
        <div className="mt-2.5">
          <div className="mb-1.5 text-sm font-semibold text-muted-foreground">Related Campaigns ({c.related_campaigns.length})</div>
          <div className="overflow-hidden rounded-md border border-border">
            {c.related_campaigns.map((rc) => {
              const hints = [...rc.shared_elements.tas.slice(0, 2), ...rc.shared_elements.ttps.slice(0, 2), ...rc.shared_elements.iocs.slice(0, 1)].join(", ");
              return (
                <button key={rc.cluster_id} type="button" onClick={() => onJumpToCampaign(rc.cluster_id)} className="flex w-full items-center gap-2 border-b border-border px-3 py-1.5 text-left last:border-b-0 hover:bg-accent">
                  <LinkTypeBadge type={rc.link_type} />
                  <span className="min-w-0 flex-1 truncate text-xs text-foreground">{rc.cluster_name}</span>
                  <span className="flex-shrink-0 font-mono text-xs text-muted-foreground">{rc.link_score}</span>
                  {hints && <span title={hints} className="max-w-[200px] flex-shrink-0 truncate font-mono text-xs text-muted-foreground">↳ {hints}</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
