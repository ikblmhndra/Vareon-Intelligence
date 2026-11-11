"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { EntityChipList } from "@/components/entities/entity-chip";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { HeatCell, HeatGrid } from "@/components/ui/heat-grid";
import { StatePanel } from "@/components/ui/state-panel";
import { heatInsight, heatStep, monthEnd, monthLong, monthShort, monthsCopy } from "@/lib/exec/heat";
import { toTitleCase } from "@/lib/exec/format";
import { actorChips } from "@/lib/entities/article-refs";
import { fmtShortDate } from "@/lib/format";
import { newsroomHref } from "@/lib/newsroom/links";
import { cn } from "@/lib/utils";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

// Kelas ditulis utuh (Tailwind). Langkah 2..5 `SCALE` di heat-grid; swatch pertama = sel kosong berbingkai.
const LEGEND_SWATCH = [
  "border border-border bg-background",
  "bg-primary/20",
  "bg-primary/30",
  "bg-primary/45",
  "bg-primary",
] as const;

const FOCUS =
  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/** Kartu "Sector heatmap" (6.2): grid sektor × bulan dengan angka di tiap sel tak kosong (D11), navigasi panah,
 * Enter/klik membuka dialog drill (F16). Kolom dari `months` (C9), bukan "6 bulan" tetap. */
export function SectorHeatmap({ d, className }: { d: ExecDashboardV2; className?: string }) {
  const [drill, setDrill] = useState<{ sector: string; month: string; pos: [number, number] } | null>(null);
  const hmax = d.heatmap_max || 1;
  const insight = heatInsight(d);

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Sector heatmap</CardTitle>
        <CardDescription>Articles per sector per month, last {monthsCopy(d.months.length)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {d.sector_heatmap.length === 0 ? (
          <StatePanel variant="empty" title="No sector activity in this period" />
        ) : (
          <>
            <div className="flex items-center gap-1.5 text-2xs text-muted-foreground">
              fewer
              {LEGEND_SWATCH.map((c) => (
                <span key={c} aria-hidden="true" className={cn("size-2.5 rounded-[3px]", c)} />
              ))}
              more
            </div>
            <HeatGrid
              aria-label="Articles per sector per month"
              rowLabels={d.sector_heatmap.map((r) => (
                <span key={r.sector} className="block max-w-40 truncate" title={toTitleCase(r.sector)}>
                  {toTitleCase(r.sector)}
                </span>
              ))}
              colLabels={d.months.map(monthShort)}
              active={drill?.pos ?? null}
              onSelect={(r, c) => {
                const cell = d.sector_heatmap[r]?.months[c];
                if (cell && cell.count > 0) setDrill({ sector: d.sector_heatmap[r].sector, month: cell.month, pos: [r, c] });
              }}
              renderCell={(r, c) => {
                const row = d.sector_heatmap[r];
                const cell = row.months[c];
                const n = cell?.count ?? 0;
                const label = `${toTitleCase(row.sector)} · ${monthLong(d.months[c])}`;
                return n > 0 ? (
                  <HeatCell
                    variant="scale"
                    value={n}
                    step={heatStep(n, hmax)}
                    selected={drill?.pos[0] === r && drill.pos[1] === c}
                    aria-label={`${label}, ${n} articles`}
                    title={`${label}: ${n} — open articles`}
                  />
                ) : (
                  <HeatCell variant="scale" value={null} aria-label={`${label}, no articles`} />
                );
              }}
            />
            {insight && <p className="text-xs text-muted-foreground">{insight}</p>}
          </>
        )}
      </CardContent>
      <DrillDialog drill={drill} onClose={() => setDrill(null)} />
    </Card>
  );
}

function DrillDialog({ drill, onClose }: { drill: { sector: string; month: string } | null; onClose: () => void }) {
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
  const start = drill ? `${drill.month}-01` : "";

  return (
    <Dialog open={drill !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[80vh] w-full max-w-lg overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{drill ? `${toTitleCase(drill.sector)} · ${monthLong(drill.month)}` : ""}</DialogTitle>
          <DialogDescription>
            {query.isError
              ? "Could not load the articles."
              : query.data
                ? `${query.data.total} article${query.data.total !== 1 ? "s" : ""}`
                : "Loading…"}
          </DialogDescription>
        </DialogHeader>
        {query.data && query.data.articles.length === 0 && (
          <p className="py-6 text-center text-xs text-muted-foreground">No articles found.</p>
        )}
        <div className="space-y-3">
          {query.data?.articles.map((a) => (
            <div key={a.id} className="border-b border-border pb-3 last:border-none">
              <a
                href={a.url}
                target="_blank"
                rel="noopener noreferrer"
                className={cn("rounded-md font-medium text-foreground outline-none hover:underline", FOCUS)}
              >
                {a.title}
              </a>
              <div className="mt-1 text-xs text-muted-foreground">
                {a.source} · {fmtShortDate(a.posted_on)}
              </div>
              {a.threat_actors.length > 0 && (
                <div className="mt-1.5">
                  <EntityChipList items={actorChips(a).slice(0, 3)} />
                </div>
              )}
            </div>
          ))}
        </div>
        {drill && (
          <DialogFooter className="sm:items-center sm:justify-between">
            <p className="text-2xs text-muted-foreground">Newsroom shows articles from {fmtShortDate(start, { withYear: true })} onward.</p>
            <Link
              href={newsroomHref({ industry: drill.sector, from: start })}
              className={cn("rounded-md text-xs font-medium text-primary-text outline-none hover:underline", FOCUS)}
            >
              Open in Newsroom →
            </Link>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
