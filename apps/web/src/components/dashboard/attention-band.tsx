"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";
import { Skeleton } from "@/components/ui/skeleton";

const DAYS = 30;

/** Band burgundy "Need Attention" di atas Dashboard (Arah A): satu titik
 * fokus berisi hal yang paling mendesak, dibaca dari dashboard exec + stats CVE. */
export function AttentionBand() {
  const exec = useQuery({
    queryKey: ["attention", "exec", DAYS],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/exec/dashboard-v2", {
        params: { query: { days: DAYS, incident_only: true, confirmed_only: false } },
      });
      if (error) throw error;
      return data as unknown as ExecDashboardV2;
    },
  });
  const cve = useQuery({
    queryKey: ["attention", "cve-stats"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/cve/stats", { params: { query: {} } });
      if (error) throw error;
      return data as unknown as { critical?: number };
    },
  });

  if (exec.isPending || cve.isPending) return <Skeleton className="h-36 w-full rounded-3xl" />;
  if (exec.isError && cve.isError) return null;

  const top = exec.data?.sector_risk_scores[0];

  return (
    <section
      aria-label="Need Attention"
      className="grid gap-6 rounded-3xl bg-[#430a23] p-6 text-[#f6ede4] sm:p-8 md:grid-cols-[1.4fr_1fr_1fr_1fr] md:items-center"
    >
      <div>
        <div className="text-xs font-semibold tracking-widest text-[#fbbfa1] uppercase">Need Attention</div>
        <div className="mt-2 text-2xl leading-tight font-bold">
          {top ? `Sector ${top.sector} leads in risk` : "Current Risk Summary"}
        </div>
        <div className="mt-1 text-sm text-[#e6cfd6]">Period {DAYS} days</div>
      </div>
      <Metric value={cve.data?.critical} label="Open CVE Critical" accent />
      <Metric value={top?.risk_score} suffix="/100" label={top ? `Risk Score ${top.sector}` : "Risk Score"} />
      <Metric value={exec.data?.total_incidents} label="Incidents" />
    </section>
  );
}

function Metric({ value, label, suffix, accent }: { value: number | undefined; label: string; suffix?: string; accent?: boolean }) {
  return (
    <div>
      <div className={`text-4xl leading-none font-extrabold tracking-tight tabular-nums ${accent ? "text-[#ff8a7e]" : ""}`}>
        {value === undefined ? "—" : value.toLocaleString()}
        {value !== undefined && suffix && <span className="text-xl font-semibold text-[#e6cfd6]">{suffix}</span>}
      </div>
      <div className="mt-2 text-sm text-[#e6cfd6]">{label}</div>
    </div>
  );
}
