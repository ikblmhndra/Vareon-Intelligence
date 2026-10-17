import { StatBox } from "@/components/dashboard/stat-box";
import { cn } from "@/lib/utils";
import { execTrend } from "@/lib/exec/format";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

function TrendSub({
  current,
  prev,
  reliable,
  fallback,
}: {
  current: number;
  prev: number;
  reliable: boolean;
  fallback: string;
}) {
  // Periode sebelumnya kosong/jarang (mis. platform baru jalan): persen vs prev menyesatkan.
  if (!reliable) return <>no prior-period data</>;
  const trend = execTrend(current, prev);
  if (!trend) return <>{fallback}</>;
  return <span className={trend.colorClass}>{trend.text}</span>;
}

/** Port strip KPI (`exec.js:88-113`). */
export function KpiStrip({ d }: { d: ExecDashboardV2 }) {
  const activeSectors = d.active_sectors ?? d.top_sectors.length;
  const uniqueTas = d.unique_ta_count ?? d.ta_leaderboard.length;
  const topRisk = d.sector_risk_scores[0];
  // Satu sektor bisa muncul di beberapa hari: hitung sektornya, bukan chip-nya.
  const spikeCount = new Set(d.industry_spikes.map((s) => s.entity)).size;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 2xl:grid-cols-8">
      <StatBox
        label="Total Incidents"
        value={d.total_incidents.toLocaleString()}
        sub={<TrendSub current={d.total_incidents} prev={d.prev_total} reliable={d.prev_period_reliable} fallback="—" />}
      />
      <StatBox
        label="Active Sectors"
        value={activeSectors}
        sub={<TrendSub current={activeSectors} prev={d.prev_active_sectors} reliable={d.prev_period_reliable} fallback="—" />}
      />
      <StatBox
        label="Unique TAs"
        value={uniqueTas}
        sub={<TrendSub current={uniqueTas} prev={d.prev_unique_ta} reliable={d.prev_period_reliable} fallback="—" />}
      />
      <StatBox label="Critical CVEs" value={d.cve_kpis.critical} sub="all tracked · not period-filtered" />
      <StatBox label="KEV CVEs" value={d.cve_kpis.kev} sub="CISA known exploited · all tracked" />
      <StatBox
        label="Highest-Risk Sector"
        value={topRisk ? topRisk.sector : "—"}
        sub={topRisk ? `Risk Score: ${topRisk.risk_score}/100${d.risk_volume_only ? " · volume only" : ""}` : ""}
      />
      <StatBox label="Active Spikes" value={spikeCount} sub="sectors above baseline (z ≥ 1.5)" />
      <StatBox
        label="Confirmed Rate"
        value={d.confirmed_incident_rate != null ? `${d.confirmed_incident_rate}%` : "N/A"}
        sub={d.confirmed_incident_rate != null ? "verified by LLM" : "field not yet populated"}
      />
    </div>
  );
}

export function KpiStripSkeleton() {
  return (
    <div className={cn("grid grid-cols-2 gap-3 sm:grid-cols-4 2xl:grid-cols-8")}>
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="h-[68px] animate-pulse rounded-2xl surface-raised" />
      ))}
    </div>
  );
}
