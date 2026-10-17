"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

function toTitleCase(s: string): string {
  return s.replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
}

function monthEnd(yyyymm: string): string {
  const [y, m] = yyyymm.split("-").map(Number);
  return new Date(y, m, 0).toISOString().slice(0, 10);
}

/** Port heatmap Sector × Month + drill-down klik sel (`exec.js:291-318`,
 * `openExecDrill()` `exec.js:587-630`). */
export function SectorHeatmap({ d }: { d: ExecDashboardV2 }) {
  const [drill, setDrill] = useState<{ sector: string; month: string } | null>(null);

  if (d.sector_heatmap.length === 0) return null;
  const hmax = d.heatmap_max || 1;

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr>
              <th />
              {d.months.map((m) => (
                <th key={m} className="px-1 py-1 font-mono text-muted-foreground">
                  {m.slice(5)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {d.sector_heatmap.map((row) => (
              <tr key={row.sector}>
                <td className="px-2 py-1 font-mono whitespace-nowrap text-muted-foreground">
                  {toTitleCase(row.sector)}
                </td>
                {row.months.map((cell) => {
                  const intensity = hmax > 0 ? cell.count / hmax : 0;
                  return (
                    <td
                      key={cell.month}
                      className="px-1 py-1 text-center font-mono"
                      style={{
                        // Alfa maks 65% dengan teks tetap: >= 4.67:1 di terang dan 5.05:1 di gelap.
                        background: `color-mix(in srgb, var(--primary) ${Math.round(intensity * 60 + 5)}%, transparent)`,
                        cursor: cell.count > 0 ? "pointer" : undefined,
                      }}
                      title={`${toTitleCase(row.sector)} · ${cell.month}: ${cell.count}${cell.count > 0 ? " — click to view articles" : ""}`}
                      onClick={() => cell.count > 0 && setDrill({ sector: row.sector, month: cell.month })}
                    >
                      {cell.count || ""}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <DrillModal drill={drill} onClose={() => setDrill(null)} />
    </>
  );
}

function DrillModal({ drill, onClose }: { drill: { sector: string; month: string } | null; onClose: () => void }) {
  const query = useQuery({
    queryKey: ["exec", "drill", drill?.sector, drill?.month],
    queryFn: async () => {
      if (!drill) return null;
      const { data, error } = await api.GET("/api/articles", {
        params: {
          query: {
            industry: [drill.sector],
            posted_on_start: `${drill.month}-01`,
            posted_on_end: monthEnd(drill.month),
            page_size: 20,
          },
        },
      });
      if (error) throw error;
      return data;
    },
    enabled: drill !== null,
  });

  return (
    <Dialog open={drill !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[80vh] w-full max-w-lg overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{drill ? toTitleCase(drill.sector) : ""}</DialogTitle>
          <p className="font-mono text-xs text-muted-foreground">
            {drill?.month}
            {query.data ? ` · ${query.data.total} article${query.data.total !== 1 ? "s" : ""}` : " — loading…"}
          </p>
        </DialogHeader>
        {query.data && query.data.articles.length === 0 && (
          <p className="py-6 text-center text-xs text-muted-foreground">No articles found.</p>
        )}
        <div className="space-y-3">
          {query.data?.articles.map((a) => (
            <div key={a.id} className="border-b border-border pb-3 last:border-none">
              <a href={a.url} target="_blank" rel="noopener noreferrer" className="font-medium text-foreground hover:underline">
                {a.title}
              </a>
              <div className="mt-1 flex flex-wrap gap-2 font-mono text-xs text-muted-foreground">
                <span>{a.posted_on}</span>
                <span>{a.source}</span>
                {a.news_type && <span className="text-primary">{a.news_type}</span>}
                {a.threat_actors.length > 0 && (
                  <span className="text-warning">{a.threat_actors.slice(0, 3).map(toTitleCase).join(", ")}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
