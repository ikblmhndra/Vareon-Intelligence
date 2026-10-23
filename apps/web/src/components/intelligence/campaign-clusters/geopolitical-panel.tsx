"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { TrendingUpIcon, TriangleAlertIcon } from "lucide-react";

import { api } from "@/lib/api/client";
import type { GeopoliticalSummary } from "@/lib/api/loose-types";

const MOTIVATION_COLOR: Record<string, string> = {
  espionage: "var(--tag-violet)",
  financial: "var(--severity-high)",
  ransomware: "var(--severity-critical)",
  hacktivism: "var(--success)",
  sabotage: "var(--severity-critical)",
  unknown: "var(--muted-foreground)",
};

/** Port "GEOPOLITICAL OVERVIEW" (`clusters.js:766-907`) -- panel
 * collapsible di dalam view Campaigns (BUKAN sub-view terpisah),
 * `GET /api/intelligence/geopolitical` terima `campaigns` Pipeline 2.
 * **Catatan nuansa data** (bukan bug baru, warisan Fase 7.4 Grup A):
 * `nation_state_activity[nation].targeted_sectors` backend DEDUP per
 * nation, beda dari legacy yang gak dedup -- heatmap nation×sector di
 * sini jadi biner (terisi/kosong) bukan gradasi intensitas kayak
 * niat aslinya, karena gak ada duplikat buat dihitung. Port apa
 * adanya (logic hitung `.filter(x => x === s).length` sama persis),
 * cuma hasil visualnya beda dari desain original akibat data shape
 * yang udah di-dedup di backend. */
export function GeopoliticalPanel({ days }: { days: number }) {
  const [open, setOpen] = useState(false);

  const query = useQuery({
    queryKey: ["campaign-clusters", "geopolitical", days],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/intelligence/geopolitical", { params: { query: { days } } });
      if (error) throw error;
      return data as unknown as GeopoliticalSummary;
    },
    enabled: open,
  });

  const d = query.data;
  const nations = d ? Object.keys(d.nation_state_activity).filter((n) => n !== "Unknown").sort() : [];
  const sectors = d ? [...new Set(nations.flatMap((n) => d.nation_state_activity[n].targeted_sectors))].sort() : [];
  const maxCount = Math.max(1, ...nations.flatMap((n) => sectors.map((s) => (d!.nation_state_activity[n].targeted_sectors.filter((x) => x === s).length))));
  const motEntries = d ? Object.entries(d.motivation_breakdown).sort((a, b) => b[1] - a[1]) : [];
  const motTotal = motEntries.reduce((s, [, v]) => s + v, 0) || 1;

  return (
    <div className="mb-4 rounded-md border border-border">
      <button type="button" onClick={() => setOpen((o) => !o)} className="w-full px-3 py-2 text-left font-mono text-xs tracking-wider text-muted-foreground uppercase">
        {open ? "▾" : "▸"} Geopolitical Overview
      </button>
      {open && (
        <div className="border-t border-border p-3">
          {query.isPending && <p className="text-xs text-muted-foreground">Loading geopolitical context…</p>}
          {query.isError && <p className="text-xs text-destructive">Error loading geopolitical overview.</p>}
          {d && (
            <>
              {d.geopolitical_alerts.length > 0 && (
                <div className="mb-3.5">
                  <div className="mb-1.5 text-xs font-bold tracking-wider text-muted-foreground">ALERTS</div>
                  <div className="flex flex-col gap-1">
                    {d.geopolitical_alerts.map((a, i) => {
                      const isInc = a.includes("increased") || a.includes("converging") || a.includes("New threat");
                      return (
                        <div key={i} className={`rounded-md border px-2.5 py-1.5 font-mono text-xs text-foreground ${isInc ? "border-destructive/40 bg-destructive/12" : "border-warning/35 bg-warning/10"}`}>
                          {isInc ? (
                            <TrendingUpIcon className="mr-1 inline size-3.5 align-[-2px] text-destructive-text" aria-hidden />
                          ) : (
                            <TriangleAlertIcon className="mr-1 inline size-3.5 align-[-2px] text-warning-text" aria-hidden />
                          )}
                          <span className="sr-only">{isInc ? "Increase: " : "Notice: "}</span>
                          {a}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {nations.length > 0 && sectors.length > 0 && (
                <div className="mb-3.5">
                  <div className="mb-1.5 text-xs font-bold tracking-wider text-muted-foreground">NATION → SECTOR HEATMAP</div>
                  <div className="overflow-x-auto">
                    <table className="border-collapse text-xs">
                      <thead>
                        <tr>
                          <th className="border border-border/50 px-2 py-1 text-left font-mono text-xs text-muted-foreground">Nation</th>
                          {sectors.map((s) => (
                            <th key={s} title={s} className="max-w-[80px] truncate border border-border/50 px-1.5 py-1 text-center font-mono text-xs text-muted-foreground">
                              {s.length > 12 ? `${s.slice(0, 11)}…` : s}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {nations.map((nation) => {
                          const entry = d.nation_state_activity[nation];
                          return (
                            <tr key={nation}>
                              <td className="border border-border/50 px-2 py-1 font-mono text-xs font-semibold whitespace-nowrap text-foreground">
                                {nation}
                                {entry.primary_motivations.slice(0, 1).map((m) => (
                                  <span key={m} className="ml-1 rounded-full border border-tag-violet/40 bg-tag-violet/20 px-1 py-0.5 font-mono text-xs text-tag-violet-text">
                                    {m}
                                  </span>
                                ))}
                              </td>
                              {sectors.map((sector) => {
                                const count = entry.targeted_sectors.filter((x) => x === sector).length;
                                if (!count) return <td key={sector} className="border border-border/30 bg-background/30" />;
                                const alpha = Math.round((count / maxCount) * 0.7 * 100) / 100 + 0.08;
                                return (
                                  <td key={sector} className="border border-destructive/25 text-center font-mono text-xs font-bold text-foreground" style={{ background: `color-mix(in srgb, var(--severity-critical) ${Math.round(alpha * 100)}%, transparent)` }}>
                                    {count}
                                  </td>
                                );
                              })}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {motEntries.length > 0 && (
                <div className="mb-1">
                  <div className="mb-1.5 text-xs font-bold tracking-wider text-muted-foreground">MOTIVATION BREAKDOWN</div>
                  {motEntries.map(([mot, cnt]) => {
                    const pct = Math.round((cnt / motTotal) * 100);
                    const color = MOTIVATION_COLOR[mot] ?? "var(--muted-foreground)";
                    return (
                      <div key={mot} className="mb-0.5 flex items-center gap-1.5">
                        <span className="w-20 flex-shrink-0 font-mono text-xs text-muted-foreground">{mot}</span>
                        <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-background">
                          <div className="h-full rounded-full opacity-80" style={{ width: `${pct}%`, background: color }} />
                        </div>
                        <span className="w-7 flex-shrink-0 text-right font-mono text-xs text-muted-foreground">{cnt}</span>
                      </div>
                    );
                  })}
                </div>
              )}

              <div className="mt-1 text-right font-mono text-xs text-muted-foreground">
                {d.campaign_count} campaigns · {d.days}d window
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
