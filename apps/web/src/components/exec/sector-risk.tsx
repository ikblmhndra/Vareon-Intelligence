import { cn } from "@/lib/utils";
import { riskTier, sectorPeerBenchmark } from "@/lib/exec/format";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

function toTitleCase(s: string): string {
  return s.replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
}

const RISK_FORMULA_TITLE =
  "Risk Score = Volume(0-50) + Trend(0-20) + Spike(0-30)\n• Volume: (last_month / max_sector) × 50\n• Trend: increase first→second half, max 20\n• Spike: z-score × 10, capped at 30";

/** Port Sector Risk Matrix + peer benchmark (`exec.js:135-167`). */
export function SectorRiskMatrix({ d }: { d: ExecDashboardV2 }) {
  return (
    <div className="space-y-2 rounded-2xl border border-border bg-surface p-5 shadow-sm">
      {d.sector_risk_scores.map((sr) => {
        const tier = riskTier(sr.risk_score);
        const bench = sectorPeerBenchmark(d.sector_trend, sr.sector);
        return (
          <div key={sr.sector} className="flex items-center gap-2.5" title={RISK_FORMULA_TITLE}>
            <div className="min-w-[140px] truncate font-mono text-xs text-foreground">{toTitleCase(sr.sector)}</div>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                className={cn("h-full rounded-full", tier.colorClass.replace("text-", "bg-"))}
                style={{ width: `${sr.risk_score}%` }}
              />
            </div>
            <div className={cn("min-w-[28px] text-right font-mono text-xs", tier.colorClass)}>{sr.risk_score}</div>
            <div
              className={cn(
                "min-w-[32px] rounded px-1.5 py-0.5 text-center font-mono text-xs",
                tier.colorClass,
                tier.colorClass.replace("text-", "bg-") + "/15",
              )}
            >
              {tier.label}
            </div>
            <div
              className={cn("min-w-[64px] text-right font-mono text-xs", bench.colorClass)}
              title="Peer Benchmark: share of total incidents vs avg sector share"
            >
              {bench.text}
            </div>
          </div>
        );
      })}
      {/* Catatan penyebut: apa yang TIDAK ikut peringkat, dan kenapa skornya bisa tampak datar. */}
      {d.sector_unspecified > 0 && (
        <p className="pt-1 font-mono text-xs text-muted-foreground">
          {d.sector_unspecified.toLocaleString()} of {d.total_incidents.toLocaleString()} incidents have no
          specific sector (General) and are not ranked.
        </p>
      )}
      {d.risk_volume_only && (
        <p className="font-mono text-xs text-muted-foreground">
          Score = volume only: trend and spike components stay off until at least two earlier months have
          enough data.
        </p>
      )}
    </div>
  );
}
