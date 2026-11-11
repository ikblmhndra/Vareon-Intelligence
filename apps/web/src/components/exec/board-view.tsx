"use client";

import { DashboardSectionLabel } from "@/components/dashboard/stat-box";
import { NewsTypesCard, SectorTrendCard, VictimCountryTrendCard } from "@/components/exec/charts-section";
import { ExecKpiRow } from "@/components/exec/exec-kpi-row";
import { ActorSectorDots } from "@/components/exec/actor-sector-dots";
import { ActorVelocityCard } from "@/components/exec/actor-velocity-card";
import { ExecLegacySignalCharts } from "@/components/exec/charts-section";
import { QueuesRow } from "@/components/exec/role-gated-panels";
import { SectorHeatmap } from "@/components/exec/sector-heatmap";
import type { ExecFilters } from "@/lib/exec/filters";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

/** Tampilan Analyst board (6.2) dalam urutan spec: KPI, heatmap + News types, dua tren, matriks aktor-sektor +
 * velocity, baris antrean (gerbang peran), lalu "More signals". CVE exposure dan Top techniques ada di Briefing
 * (6.1), bukan di board. */
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

      <DashboardSectionLabel>Secondary Signals</DashboardSectionLabel>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ActorSectorDots matrix={d.sector_actor_matrix} />
        <ActorVelocityCard d={d} />
      </div>

      <QueuesRow d={d} />
      <DashboardSectionLabel>More signals</DashboardSectionLabel>
      <ExecLegacySignalCharts d={d} />
    </>
  );
}
