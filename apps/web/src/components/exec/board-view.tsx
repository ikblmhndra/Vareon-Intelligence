"use client";

import { DashboardSectionLabel } from "@/components/dashboard/stat-box";
import { CveExposureCard } from "@/components/exec/cve-exposure-card";
import { ExecLegacySignalCharts, NewsTypesCard, SectorTrendCard, VictimCountryTrendCard } from "@/components/exec/charts-section";
import { ExecKpiRow } from "@/components/exec/exec-kpi-row";
import { ActorSectorDots } from "@/components/exec/actor-sector-dots";
import { ActorVelocityCard } from "@/components/exec/actor-velocity-card";
import { SectorHeatmap } from "@/components/exec/sector-heatmap";
import { ClusterList, CriticalCveFeed, FpQueue } from "@/components/exec/role-gated-panels";
import { TopTechniquesCard } from "@/components/exec/top-techniques-card";
import type { ExecFilters } from "@/lib/exec/filters";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

/** Tampilan Analyst board (6.2). Task 14 memegang baris KPI, heatmap sektor, News types, dan dua tren; blok
 * di bawahnya (CVE exposure, Top techniques, matriks aktor, velocity, co-targeted, antrean, klaster, grafik
 * sinyal) adalah isi lama yang dimiliki Task 15-17 dan dirender apa adanya sampai tiap task menggantinya. */
export function BoardView({ d, filters }: { d: ExecDashboardV2; filters: ExecFilters }) {
  return (
    <>
      <ExecKpiRow d={d} filters={filters} tiles="board" />

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SectorHeatmap d={d} />
        <NewsTypesCard d={d} filters={filters} />
        <SectorTrendCard d={d} />
        <VictimCountryTrendCard d={d} />
      </div>

      {/* --- Isi lama, dimiliki Task 15-17 --- */}
      <DashboardSectionLabel>CVE Exposure</DashboardSectionLabel>
      <p className="-mt-2 mb-2 text-xs text-muted-foreground">
        All tracked CVEs across clients (false positives excluded), not filtered by the period above.
      </p>
      <CveExposureCard d={d} />

      <DashboardSectionLabel>Secondary Signals</DashboardSectionLabel>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <TopTechniquesCard d={d} days={filters.days} />
        <ActorSectorDots matrix={d.sector_actor_matrix} />
        <ActorVelocityCard d={d} />
      </div>

      {(d.view_config.sections.cluster_list || d.view_config.sections.fp_feedback_queue || d.view_config.sections.critical_cve_feed) && (
        <>
          <DashboardSectionLabel>Role View — {d.view_config.role.toUpperCase()}</DashboardSectionLabel>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {d.view_config.sections.cluster_list && (
              <div className="rounded-xl border border-border bg-background p-3">
                <div className="mb-2 font-mono text-xs text-muted-foreground">Recent Campaign Clusters</div>
                <ClusterList d={d} />
              </div>
            )}
            {d.view_config.sections.fp_feedback_queue && (
              <div className="rounded-xl border border-border bg-background p-3">
                <div className="mb-2 font-mono text-xs text-muted-foreground">IOC False-Positive Queue</div>
                <FpQueue d={d} />
              </div>
            )}
            {d.view_config.sections.critical_cve_feed && (
              <div className="rounded-xl border border-border bg-background p-3 lg:col-span-2">
                <div className="mb-2 font-mono text-xs text-muted-foreground">KEV CVE Feed — CISA known exploited</div>
                <CriticalCveFeed d={d} />
              </div>
            )}
          </div>
        </>
      )}

      <DashboardSectionLabel>More signals</DashboardSectionLabel>
      <ExecLegacySignalCharts d={d} />
    </>
  );
}
