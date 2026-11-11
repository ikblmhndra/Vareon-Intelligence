import { EntityChip } from "@/components/entities/entity-chip";
import { cn } from "@/lib/utils";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

function toTitleCase(s: string): string {
  return s.replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
}

/** Port TA Velocity (`exec.js:372-392`). */
export function TaVelocity({ d }: { d: ExecDashboardV2 }) {
  if (d.ta_velocity.length === 0) {
    return <p className="py-2 font-mono text-xs text-muted-foreground">Not enough history yet — needs an earlier month with enough data</p>;
  }
  return (
    <div className="space-y-1.5">
      {d.ta_velocity.map((ta) => {
        const isRising = ta.velocity_pct > 0;
        const isNew = ta.avg_prev === 0;
        const colorClass = isNew ? "text-success" : isRising ? "text-destructive" : "text-muted-foreground";
        const arrow = isNew ? "" : isRising ? "▲" : "▼";
        const label = isNew ? "NEW" : `${isRising ? "+" : ""}${ta.velocity_pct}%`;
        return (
          <div key={ta.actor} className="flex items-center gap-2.5">
            <div className="min-w-[140px]">
              <EntityChip type="intrusion-set" name={ta.actor} label={toTitleCase(ta.actor)} />
            </div>
            <div className={cn("min-w-[48px] font-mono text-xs", colorClass)}>
              {arrow} {label}
            </div>
            <div className="font-mono text-xs text-muted-foreground">
              last: {ta.last_month} · avg: {ta.avg_prev}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Port Sector Co-occurrence (`exec.js:450-469`). */
export function SectorCooccurrence({ d }: { d: ExecDashboardV2 }) {
  if (d.sector_cooccurrence.length === 0) {
    return <p className="font-mono text-xs text-muted-foreground">No co-targeting data</p>;
  }
  const maxCo = d.sector_cooccurrence[0]?.count || 1;
  return (
    <div className="space-y-1.5">
      {d.sector_cooccurrence.map((co, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            <EntityChip type="identity" name={co.sector_a} label={toTitleCase(co.sector_a)} />
            <span aria-label="co-targeted with" className="shrink-0 text-primary">
              ↔
            </span>
            <EntityChip type="identity" name={co.sector_b} label={toTitleCase(co.sector_b)} />
          </div>
          <div className="h-1.5 w-15 shrink-0 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary/50" style={{ width: `${Math.round((co.count / maxCo) * 100)}%` }} />
          </div>
          <span className="min-w-[20px] text-right font-mono text-xs text-muted-foreground">{co.count}</span>
        </div>
      ))}
    </div>
  );
}
