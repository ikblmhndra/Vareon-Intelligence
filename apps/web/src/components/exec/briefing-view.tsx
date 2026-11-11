import type { ReactNode } from "react";

import { DashboardSectionLabel } from "@/components/dashboard/stat-box";
import { ExecChartsSection } from "@/components/exec/charts-section";
import { ExecKpiRow } from "@/components/exec/exec-kpi-row";
import { SectorRiskMatrix } from "@/components/exec/sector-risk";
import { SectorSpikesHero } from "@/components/exec/sector-spikes-hero";
import { TaLeaderboard } from "@/components/exec/ta-leaderboard";
import type { ExecFilters } from "@/lib/exec/filters";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

/** Tampilan Briefing: baris utama (brief + spike sektor), baris KPI, lalu baris-baris Task 11. Sampai Task 11
 * selesai, bagian lama (risk matrix, leaderboard, tren) tetap dirender di bawah supaya tidak ada fitur hilang.
 * `brief` kosong (Task 12 belum ada) -> panel spike memakai lebar penuh. */
export function BriefingView({ d, filters, brief }: { d: ExecDashboardV2; filters: ExecFilters; brief: ReactNode }) {
  return (
    <>
      <div className={brief ? "grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]" : undefined}>
        {brief}
        <SectorSpikesHero d={d} />
      </div>
      <ExecKpiRow d={d} filters={filters} tiles="briefing" />

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div>
          <DashboardSectionLabel>Sector Risk Matrix</DashboardSectionLabel>
          <SectorRiskMatrix d={d} />
        </div>
        <div>
          <DashboardSectionLabel>Threat Actor Leaderboard</DashboardSectionLabel>
          <TaLeaderboard d={d} />
        </div>
      </div>

      <DashboardSectionLabel>Trends</DashboardSectionLabel>
      <ExecChartsSection d={d} />
    </>
  );
}
