import type { ReactNode } from "react";

import { DashboardSectionLabel } from "@/components/dashboard/stat-box";
import { ExecChartsSection } from "@/components/exec/charts-section";
import { ExecKpiRow } from "@/components/exec/exec-kpi-row";
import { CveExposureCard } from "@/components/exec/cve-exposure-card";
import { SectorRiskCard } from "@/components/exec/sector-risk-card";
import { SectorSpikesHero } from "@/components/exec/sector-spikes-hero";
import { ThreatActorsCard } from "@/components/exec/threat-actors-card";
import { TopTechniquesCard } from "@/components/exec/top-techniques-card";
import { execWindowFrom } from "@/lib/exec/format";
import type { ExecFilters } from "@/lib/exec/filters";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

/** Tampilan Briefing: baris utama (brief + spike sektor), baris KPI, dua baris kartu (Sector risk | Threat
 * actors, CVE exposure | Top techniques) lalu tren. Tren (`ExecChartsSection`) masih tinggal di sini sampai
 * Analyst board (Task 14) mengambilnya, jadi tidak ada grafik yang hilang. `today` dari halaman, bukan
 * `new Date()` di render, supaya `from` tautan Newsroom stabil dan sama dengan rentang di header.
 * `brief` kosong (Task 12 belum ada) -> panel spike memakai lebar penuh. */
export function BriefingView({
  d,
  filters,
  brief,
  today,
}: {
  d: ExecDashboardV2;
  filters: ExecFilters;
  brief: ReactNode;
  today: Date;
}) {
  const from = execWindowFrom(filters.days, today);
  return (
    <>
      <div className={brief ? "grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]" : undefined}>
        {brief}
        <SectorSpikesHero d={d} />
      </div>
      <ExecKpiRow d={d} filters={filters} tiles="briefing" />

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-5">
        <SectorRiskCard d={d} className="lg:col-span-3" />
        <ThreatActorsCard d={d} from={from} className="lg:col-span-2" />
        <CveExposureCard d={d} className="lg:col-span-3" />
        <TopTechniquesCard d={d} days={filters.days} className="lg:col-span-2" />
      </div>

      <DashboardSectionLabel>Trends</DashboardSectionLabel>
      <ExecChartsSection d={d} />
    </>
  );
}
