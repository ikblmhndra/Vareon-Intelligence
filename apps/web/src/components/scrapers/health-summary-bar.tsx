"use client";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";
import { StatTile } from "@/components/ui/stat-tile";
import { browserZoneName, fmtTime } from "@/lib/format";
import { statusTileTone } from "@/components/scrapers/status-badge";

const TILES = [
  { status: "ok", label: "OK" },
  { status: "degraded", label: "DEGRADED" },
  { status: "stale", label: "STALE" },
  { status: "zero_yield", label: "ZERO YIELD" },
  { status: "dead", label: "DEAD" },
  { status: "disabled", label: "DISABLED" },
] as const;

/** Enam tile kesehatan armada (`GET /api/scraper/health`). Klik tile = filter Status di tabel (klik lagi
 * = kembali ke "all"); `selected` adalah nilai filter Status yang aktif. */
export function HealthTiles({
  counts,
  generatedAt,
  state,
  selected,
  onSelect,
  onRetry,
}: {
  counts: Record<string, number>;
  generatedAt: string | null;
  state: "loading" | "error" | "ready";
  selected: string;
  onSelect: (status: string) => void;
  onRetry: () => void;
}) {
  return (
    <div className="mb-4">
      <div className="grid grid-cols-3 gap-3 lg:grid-cols-6">
        {TILES.map((t) =>
          state === "loading" ? (
            <Skeleton key={t.status} className="h-[88px] rounded-lg" />
          ) : (
            <StatTile
              key={t.status}
              label={t.label}
              tone={statusTileTone(t.status)}
              value={<span className="font-code">{state === "error" ? "–" : (counts[t.status] ?? 0)}</span>}
              selected={selected === t.status}
              onSelect={() => onSelect(t.status)}
              className="w-full"
            />
          ),
        )}
      </div>
      {state === "ready" && generatedAt && (
        <p className="mt-2 text-2xs text-muted-foreground">
          Health as of {fmtTime(generatedAt)} {browserZoneName()} · refreshes every minute
        </p>
      )}
      {state === "error" && (
        <Notice
          tone="warning"
          title="Scraper health could not be loaded"
          className="mt-3"
          action={
            <Button variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          }
        >
          Enabled scrapers show UNKNOWN instead of a status.
        </Notice>
      )}
    </div>
  );
}
