import { StatTile } from "@/components/ui/stat-tile";
import { execCountLabel, type ExecFilters } from "@/lib/exec/filters";
import { execDelta, toTitleCase } from "@/lib/exec/format";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

/** "{±n}% vs prev {days} d". Briefing memakai bentuk ringkas untuk selisih absolut ("{±n} vs prev"), board
 * bentuk panjang (C13): `longSuffix` menambahkan jumlah hari. Periode sebelumnya jarang -> "no prior-period data". */
function DeltaSub({
  current,
  prev,
  mode,
  days,
  reliable,
  longSuffix,
}: {
  current: number;
  prev: number;
  mode: "percent" | "absolute";
  days: number;
  reliable: boolean;
  longSuffix: boolean;
}) {
  if (!reliable) return <>no prior-period data</>;
  const delta = execDelta(current, prev, mode);
  if (!delta) return <>—</>;
  return (
    <>
      <span className={delta.colorClass}>{delta.text}</span>
      {mode === "percent" || longSuffix ? ` vs prev ${days} d` : " vs prev"}
    </>
  );
}

/** Nilai teks panjang (nama sektor) tidak muat di ukuran angka StatTile. */
function TextValue({ children }: { children: string }) {
  return (
    <span className="block text-lg leading-tight" title={children}>
      {children}
    </span>
  );
}

/** Baris KPI Exec. `briefing` = delapan tile (6.1), `board` = empat tile besar (6.2, C13). */
export function ExecKpiRow({
  d,
  filters,
  tiles,
}: {
  d: ExecDashboardV2;
  filters: Pick<ExecFilters, "days" | "incidentOnly" | "confirmedOnly">;
  tiles: "briefing" | "board";
}) {
  const label = execCountLabel(filters);
  const reliable = d.prev_period_reliable;
  const activeSectors = d.active_sectors ?? d.top_sectors.length;
  const uniqueTas = d.unique_ta_count ?? d.ta_leaderboard.length;
  const rate = d.confirmed_incident_rate;
  const board = tiles === "board";

  const countTile = (
    <StatTile
      label={label.toUpperCase()}
      value={d.total_incidents.toLocaleString()}
      sub={
        <DeltaSub current={d.total_incidents} prev={d.prev_total} mode="percent" days={filters.days} reliable={reliable} longSuffix={board} />
      }
      spark={board ? d.monthly_totals : undefined}
    />
  );
  const taTile = (
    <StatTile
      label={board ? "UNIQUE THREAT ACTORS" : "UNIQUE TAs"}
      value={uniqueTas}
      sub={
        <>
          <DeltaSub current={uniqueTas} prev={d.prev_unique_ta} mode="absolute" days={filters.days} reliable={reliable} longSuffix={board} />
          {board && d.ta_leaderboard[0] && (
            <span className="block">
              top: {toTitleCase(d.ta_leaderboard[0].name)} · {d.ta_leaderboard[0].count}
            </span>
          )}
        </>
      }
    />
  );
  const rateTile = (
    <StatTile
      label="CONFIRMED RATE"
      value={rate != null ? `${rate}%` : "—"}
      sub={
        rate != null ? (
          <>
            verified by LLM
            {board && <span className="block">of {label.toLowerCase()}</span>}
          </>
        ) : (
          "no verified articles yet"
        )
      }
    />
  );

  if (board) {
    const topTech = [...d.cve_exposure_v2].sort((a, b) => b.critical - a.critical).slice(0, 2);
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {countTile}
        {taTile}
        <StatTile
          label={`CRITICAL CVEs · ${d.cve_kpis.kev} KEV`}
          value={d.cve_kpis.critical}
          sub={
            <>
              all tracked, no period filter
              {topTech.length > 0 && (
                <span className="block">{topTech.map((t) => `${t.tech} ${t.critical}`).join(" · ")}</span>
              )}
            </>
          }
        />
        {rateTile}
      </div>
    );
  }

  const topRisk = d.sector_risk_scores[0];
  // Satu sektor bisa muncul di beberapa hari: hitung sektornya, bukan barisnya (sama dengan baris di hero).
  const spikeCount = new Set(d.industry_spikes.map((s) => s.entity)).size;
  return (
    <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {countTile}
      <StatTile
        label="ACTIVE SECTORS"
        value={activeSectors}
        sub={<DeltaSub current={activeSectors} prev={d.prev_active_sectors} mode="absolute" days={filters.days} reliable={reliable} longSuffix={false} />}
      />
      {taTile}
      <StatTile label="CRITICAL CVEs" value={d.cve_kpis.critical} sub="all tracked" />
      <StatTile label="KEV CVEs" value={d.cve_kpis.kev} sub="CISA KEV · all tracked" />
      <StatTile
        label="TOP RISK SECTOR"
        value={topRisk ? <TextValue>{toTitleCase(topRisk.sector)}</TextValue> : "—"}
        sub={topRisk ? `risk ${topRisk.risk_score} / 100` : ""}
      />
      <StatTile label="ACTIVE SPIKES" value={spikeCount} sub="sectors, z ≥ 1.5" />
      {rateTile}
    </div>
  );
}
