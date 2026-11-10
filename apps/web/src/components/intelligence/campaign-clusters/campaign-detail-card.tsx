"use client";

import { ChevronDownIcon } from "lucide-react";
import Link from "next/link";
import { useId, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { defang } from "@/lib/intelligence/defang";
import { displayId } from "@/lib/intelligence/format";
import { fmtShortDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { MeterBar } from "@/components/ui/meter-bar";
import { MindmapWidget } from "@/components/mindmap/mindmap-widget";
import { DiamondModelView } from "@/components/intelligence/campaign-clusters/diamond-model-view";
import { GeopoliticalPanel } from "@/components/intelligence/campaign-clusters/geopolitical-panel";
import { KillChainView } from "@/components/intelligence/campaign-clusters/kill-chain-view";
import { LinkTypeBadge } from "@/components/intelligence/campaign-clusters/cluster-badges";
import type { CampaignEntry, CampaignTrend, MatchedPir, PrioritizedCve } from "@/lib/api/loose-types";
import { StatePanel } from "@/components/ui/state-panel";

const TREND_COLOR: Record<string, string> = { growing: "var(--severity-critical)", declining: "var(--success)", dormant: "var(--muted-foreground)", stable: "var(--severity-medium)" };

/** Unduh hunt pack (JSON) campaign: perilaku lama dipertahankan, hanya tombolnya pindah ke header detail. */
function downloadHuntPack(c: CampaignEntry) {
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

function TrendSparkline({ timeline, width, height }: { timeline: { date: string; count: number }[]; width: number; height: number }) {
  const counts = timeline.map((p) => p.count);
  const max = Math.max(...counts, 1);
  const min = Math.min(...counts);
  const range = max - min || 1;
  const step = width / (counts.length - 1);
  const points = counts.map((v, i) => `${(i * step).toFixed(1)},${(height - ((v - min) / range) * height).toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="overflow-visible" aria-hidden="true">
      <polyline points={points} fill="none" stroke="var(--primary)" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/** Isi bagian "Trend": di-mount hanya saat bagian dibuka, jadi query `/trends` baru jalan saat dibutuhkan. */
function TrendBody({ clusterId }: { clusterId: string }) {
  const query = useQuery({
    queryKey: ["campaign-clusters", "trend", clusterId],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/clusters/{cluster_id}/trends", { params: { path: { cluster_id: clusterId } } });
      if (error) throw error;
      return data as unknown as CampaignTrend;
    },
  });

  if (query.isPending) return <StatePanel variant="loading" title="Loading trend" className="py-6" />;
  if (query.isError) return <p className="text-destructive-text">Failed to load trend.</p>;
  const trend = query.data;
  if (!trend.timeline || trend.timeline.length < 2) return <p className="text-muted-foreground">Not enough daily data for a trend yet.</p>;
  const color = TREND_COLOR[trend.trend_direction] ?? TREND_COLOR.stable;
  const gr = trend.growth_rate != null ? `${trend.growth_rate > 0 ? "+" : ""}${trend.growth_rate}%` : "—";

  return (
    <div className="flex flex-col gap-2">
      <p className="flex flex-wrap items-center gap-2">
        <span className="font-semibold" style={{ color }}>
          {trend.trend_direction}
        </span>
        <span className="font-code" style={{ color }}>
          {gr} 7d
        </span>
        {trend.predicted_peak && <span className="text-muted-foreground">est. peak {fmtShortDate(trend.predicted_peak)}</span>}
      </p>
      <div className="flex items-center gap-3 rounded-md bg-surface px-3 py-2">
        <TrendSparkline timeline={trend.timeline} width={200} height={32} />
        <span className="text-2xs text-muted-foreground">
          {fmtShortDate(trend.timeline[0]?.date)} → {fmtShortDate(trend.timeline[trend.timeline.length - 1]?.date)}
        </span>
      </div>
    </div>
  );
}

/** Bagian lipat (tertutup default, `aria-expanded`); anak baru di-mount saat dibuka supaya query bagian
 * berat (trend, geopolitical) tidak jalan untuk campaign yang tak dibuka. */
function CollapsibleSection({ title, meta, children }: { title: string; meta?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <div className="border-t border-border">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 py-2.5 text-left text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        {title}
        {meta && <span className="text-2xs font-normal text-muted-foreground">{meta}</span>}
        <ChevronDownIcon aria-hidden className={cn("ml-auto size-4 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      <div id={panelId} hidden={!open} className="pb-3 text-xs">
        {open && children}
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return <h3 className="text-2xs font-semibold tracking-wide text-muted-foreground uppercase">{children}</h3>;
}

const SIMPLE_CVE = (id: string): PrioritizedCve => ({ cve_id: id, priority_score: 0, priority_label: "low", patch_urgency: "", cvss_score: null, in_tech_stack: false, severity: null, cisa_kev: false, poc_available: false, actively_exploited: false });
const CVE_LIMIT = 5;

/** Chip prioritas CVE: kata kecil seperti mockup ("critical patch"), bukan huruf kapital. */
function CvePriorityTag({ label }: { label: PrioritizedCve["priority_label"] }) {
  if (label === "critical_patch") return <Chip kind="status" value="open" className="normal-case">critical patch</Chip>;
  if (label === "high_priority") return <Chip kind="status" value="watch" className="normal-case">high priority</Chip>;
  return null;
}

function PrioritizedCves({ campaign: c }: { campaign: CampaignEntry }) {
  const [all, setAll] = useState(false);
  // Campaign tanpa CVE terprioritas tetap menampilkan cve_ids mentahnya (tanpa skor).
  const list = c.prioritized_cves.length > 0 ? c.prioritized_cves : c.cve_ids.map(SIMPLE_CVE);
  if (list.length === 0) return null;
  const shown = all ? list : list.slice(0, CVE_LIMIT);

  return (
    <section aria-label="Prioritized CVEs">
      <SectionLabel>Prioritized CVEs</SectionLabel>
      <ul className="mt-2 flex flex-col gap-2">
        {shown.map((cve) => {
          const score = cve.cvss_score ?? (cve.priority_score > 0 ? cve.priority_score : null);
          return (
            <li key={cve.cve_id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {score != null && <span className="w-8 font-code text-xs font-semibold text-destructive-text">{score}</span>}
              <a
                href={`https://nvd.nist.gov/vuln/detail/${cve.cve_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="font-code text-xs font-semibold text-foreground outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                {cve.cve_id}
              </a>
              <span className="ml-auto flex flex-wrap justify-end gap-1">
                <CvePriorityTag label={cve.priority_label} />
                {cve.cisa_kev && <Chip kind="cve" value="kev" />}
                {cve.actively_exploited && <Chip kind="cve" value="exploited" />}
                {cve.poc_available && <Chip kind="cve" value="poc" />}
                {cve.in_tech_stack && <Chip kind="flag" value="in tech stack" className="normal-case" />}
              </span>
            </li>
          );
        })}
      </ul>
      {list.length > CVE_LIMIT && (
        <Button variant="link" size="xs" className="mt-1 px-0" aria-expanded={all} onClick={() => setAll((v) => !v)}>
          {all ? "Show fewer" : `Show all ${list.length}`}
        </Button>
      )}
    </section>
  );
}

function PirFooter({ pirs, onOpenPir }: { pirs: MatchedPir[]; onOpenPir: (pir: MatchedPir) => void }) {
  const [more, setMore] = useState(false);
  if (pirs.length === 0) return null;
  const [first, ...rest] = pirs;
  const pirButton = "text-left outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

  return (
    <div className="border-t border-border pt-3 text-xs">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="min-w-0 flex-1">
          Matches{" "}
          <button type="button" onClick={() => onOpenPir(first)} className={cn(pirButton, "font-semibold")}>
            {displayId("PIR", first.id)} “{first.title}”
          </button>
        </p>
        <Link
          href={`/intelligence/pir?id=${first.id}`}
          className="shrink-0 font-semibold text-primary-text outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          Link to PIR →
        </Link>
      </div>
      {rest.length > 0 && (
        <>
          <Button variant="link" size="xs" className="mt-1 px-0" aria-expanded={more} onClick={() => setMore((v) => !v)}>
            {more ? "Hide other PIRs" : `+${rest.length} more PIRs`}
          </Button>
          {more && (
            <ul className="mt-1 flex flex-col gap-1">
              {rest.map((p) => (
                <li key={p.id}>
                  <button type="button" onClick={() => onOpenPir(p)} className={pirButton}>
                    <span className="font-semibold">{displayId("PIR", p.id)}</span> {p.title}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

/** Panel kanan campaign terpilih (spec 2b 6.10): judul + "Hunt pack", kill chain, diamond model, CVE
 * terprioritas, PIR yang cocok, lalu bagian lipat berurutan (D13): Severity breakdown, Trend, Member
 * articles, IOCs, Related campaigns, Mind map, Geopolitical context. Pemanggil memberi `key` = cluster_id
 * supaya bagian yang terbuka kembali tertutup saat pindah campaign.
 *
 * Mind map memakai `MindmapWidget` apa adanya (ia sudah punya tombol tampil/sembunyi sendiri, jadi tidak
 * dibungkus bagian lipat lagi supaya tak ada dua tombol untuk satu hal).
 *
 * Chip CVE membuka NVD (deviasi lama dari legacy `openCveDetail()`: `/cve` adalah route terpisah, tak ada
 * state lintas-halaman untuk membuka modal CVE Tracker dari sini). */
export function CampaignDetailCard({
  campaign: c,
  days,
  onOpenArticle,
  onOpenPir,
  onSelectCampaign,
}: {
  campaign: CampaignEntry;
  days: number;
  onOpenArticle: (articleId: number) => void;
  onOpenPir: (pir: MatchedPir) => void;
  onSelectCampaign: (clusterId: string) => void;
}) {
  const bd = c.severity_breakdown;
  const factors: [string, number, number, string][] = [
    ["TA sophistication", bd.ta_sophistication, bd.raw.ta_sophistication, "30%"],
    ["IOC confidence", bd.ioc_confidence, bd.raw.ioc_confidence, "20%"],
    ["CVE criticality", bd.cve_criticality, bd.raw.cve_criticality, "20%"],
    ["Campaign velocity", bd.campaign_velocity, bd.raw.campaign_velocity, "15%"],
    ["Source quality", bd.source_quality, bd.raw.source_quality, "15%"],
  ];

  return (
    <Card>
      <div className="flex flex-col gap-4 px-5">
        <div className="flex flex-col gap-1">
          <div className="flex items-start gap-3">
            <h2 className="min-w-0 flex-1 font-heading text-lg font-semibold">{c.summary_title || c.cluster_id}</h2>
            <Button variant="outline" size="sm" onClick={() => downloadHuntPack(c)}>
              Hunt pack
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            First seen {fmtShortDate(c.first_seen)} · last seen {fmtShortDate(c.last_seen)} · {c.new_iocs_24h} new IOCs in 24 h
          </p>
        </div>

        <KillChainView killChain={c.kill_chain} />
        <DiamondModelView model={c.diamond_model} />
        <PrioritizedCves campaign={c} />
        <PirFooter pirs={c.matched_pirs} onOpenPir={onOpenPir} />

        <div>
          <CollapsibleSection title="Severity breakdown" meta={`${c.severity_label.toUpperCase()} ${c.severity_score}`}>
            <div className="flex flex-col gap-2">
              {factors.map(([name, contrib, raw, weight]) => (
                <div key={name} className="flex items-center gap-3">
                  <span className="w-40 shrink-0 text-muted-foreground">
                    {name} ({weight})
                  </span>
                  <MeterBar aria-label={`${name} raw score`} value={Math.round(raw)} max={100} tone="primary" className="flex-1" />
                  <span className="w-12 shrink-0 text-right font-code text-foreground">+{contrib}</span>
                </div>
              ))}
            </div>
          </CollapsibleSection>

          <CollapsibleSection title="Trend">
            <TrendBody clusterId={c.cluster_id} />
          </CollapsibleSection>

          <CollapsibleSection title={`Member articles (${c.member_article_ids.length})`}>
            {c.member_article_ids.length === 0 ? (
              <p className="text-muted-foreground">None</p>
            ) : (
              <ul className="max-h-48 overflow-y-auto rounded-md border border-border">
                {c.member_article_ids.map((aid, i) => (
                  <li key={aid} className="border-b border-border last:border-b-0">
                    <button
                      type="button"
                      onClick={() => onOpenArticle(aid)}
                      className="block w-full px-3 py-1.5 text-left text-xs text-foreground outline-none hover:bg-surface focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {c.titles[i] || aid}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </CollapsibleSection>

          <CollapsibleSection title={`IOCs (${c.iocs.length})`}>
            {c.iocs.length === 0 ? (
              <p className="text-muted-foreground">None</p>
            ) : (
              <div className="flex flex-wrap gap-1">
                {c.iocs.slice(0, 20).map((ioc, i) => (
                  <span key={i} title={ioc.type} className="rounded-[6px] bg-destructive/10 px-1.5 py-0.5 font-code text-2xs text-destructive-text">
                    {defang(ioc.type, ioc.value)}
                  </span>
                ))}
                {c.iocs.length > 20 && <span className="self-center text-muted-foreground">+{c.iocs.length - 20} more</span>}
              </div>
            )}
          </CollapsibleSection>

          <CollapsibleSection title={`Related campaigns (${c.related_campaigns.length})`}>
            {c.related_campaigns.length === 0 ? (
              <p className="text-muted-foreground">None</p>
            ) : (
              <ul className="overflow-hidden rounded-md border border-border">
                {c.related_campaigns.map((rc) => {
                  const hints = [...rc.shared_elements.tas.slice(0, 2), ...rc.shared_elements.ttps.slice(0, 2), ...rc.shared_elements.iocs.slice(0, 1)].join(", ");
                  return (
                    <li key={rc.cluster_id} className="border-b border-border last:border-b-0">
                      <button
                        type="button"
                        onClick={() => onSelectCampaign(rc.cluster_id)}
                        className="flex w-full items-center gap-2 px-3 py-1.5 text-left outline-none hover:bg-surface focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <LinkTypeBadge type={rc.link_type} />
                        <span className="min-w-0 flex-1 truncate text-xs text-foreground">{rc.cluster_name}</span>
                        <span className="shrink-0 font-code text-2xs text-muted-foreground">{rc.link_score}</span>
                        {hints && (
                          <span title={hints} className="max-w-40 shrink-0 truncate text-2xs text-muted-foreground">
                            ↳ {hints}
                          </span>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </CollapsibleSection>

          <div className="border-t border-border pt-3">
            <MindmapWidget featureType="cluster" docId={c.cluster_id} title={c.cluster_name} />
          </div>

          <CollapsibleSection title="Geopolitical context" meta={`all campaigns, ${days} days`}>
            <GeopoliticalPanel days={days} />
          </CollapsibleSection>
        </div>
      </div>
    </Card>
  );
}
