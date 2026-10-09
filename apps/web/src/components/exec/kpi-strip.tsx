import { StatBox } from "@/components/dashboard/stat-box";
import { cn } from "@/lib/utils";
import { execTrend } from "@/lib/exec/format";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

function TrendSub({ current, prev, fallback }: { current: number; prev: number; fallback: string }) {
  const trend = execTrend(current, prev);
  if (!trend) return <>{fallback}</>;
  return <span className={trend.colorClass}>{trend.text}</span>;
}

/** Port strip KPI (`exec.js:88-113`). */
export function KpiStrip({ d }: { d: ExecDashboardV2 }) {
  const activeSectors = d.active_sectors ?? d.top_sectors.length;
  const uniqueTas = d.unique_ta_count ?? d.ta_leaderboard.length;
  const topRisk = d.sector_risk_scores[0];
  const spikeCount = d.industry_spikes.length;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 2xl:grid-cols-8">
      <StatBox
        label="Total Incidents"
        value={d.total_incidents.toLocaleString()}
        sub={<TrendSub current={d.total_incidents} prev={d.prev_total} fallback="—" />}
      />
      <StatBox
        label="Active Sectors"
        value={activeSectors}
        sub={<TrendSub current={activeSectors} prev={d.prev_active_sectors} fallback="—" />}
      />
      <StatBox
        label="Unique TAs"
        value={uniqueTas}
        sub={<TrendSub current={uniqueTas} prev={d.prev_unique_ta} fallback="—" />}
      />
      <StatBox label="Critical CVEs" value={d.cve_kpis.critical} sub="by CVSS severity" />
      <StatBox label="KEV CVEs" value={d.cve_kpis.kev} sub="CISA known exploited" />
      <StatBox
        label="Highest-Risk Sector"
        value={topRisk ? topRisk.sector : "—"}
        sub={topRisk ? `Risk Score: ${topRisk.risk_score}/100` : ""}
      />
      <StatBox label="Active Spikes" value={spikeCount} sub="statistically significant" />
      <StatBox
        label="Confirmed Rate"
        value={d.confirmed_incident_rate != null ? `${d.confirmed_incident_rate}%` : "N/A"}
        sub={d.confirmed_incident_rate != null ? "verified by GPT-4o" : "field not yet populated"}
      />
    </div>
  );
}

export function KpiStripSkeleton() {
  return (
    <div className={cn("grid grid-cols-2 gap-3 sm:grid-cols-4 2xl:grid-cols-8")}>
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="h-[68px] animate-pulse rounded-2xl border border-border bg-surface shadow-sm" />
      ))}
    </div>
  );
}
