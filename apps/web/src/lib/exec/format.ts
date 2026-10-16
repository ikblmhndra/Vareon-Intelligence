/** Port `_execTrend()` (`exec.js:11-19`) -- buat metrik keamanan: naik =
 * lebih banyak insiden/aktor = BURUK (merah), turun = baik (hijau). */
export function execTrend(current: number, prev: number): { text: string; colorClass: string } | null {
  if (!prev) return null;
  const delta = current - prev;
  const pct = Math.abs(Math.round((delta / prev) * 100));
  const colorClass = delta > 0 ? "text-destructive" : delta < 0 ? "text-success" : "text-muted-foreground";
  const arrow = delta > 0 ? "↑" : delta < 0 ? "↓" : "→";
  return { text: `${arrow}${pct}% vs prev period`, colorClass };
}

export function riskTier(score: number): { label: string; colorClass: string } {
  if (score >= 70) return { label: "HIGH", colorClass: "text-destructive" };
  if (score >= 40) return { label: "MED", colorClass: "text-warning" };
  return { label: "LOW", colorClass: "text-success" };
}

/** Port peer benchmark (`exec.js:138-154`) -- share sektor ini dari total
 * insiden semua sektor (dari `sector_trend`) vs rata-rata share per
 * sektor, murni dihitung client-side (gak dibalikin API). */
export function sectorPeerBenchmark(
  sectorTrend: { sector: string; data: number[] }[],
  sector: string,
): { text: string; colorClass: string } {
  const totals = sectorTrend.map((s) => ({ sector: s.sector, total: s.data.reduce((a, b) => a + b, 0) }));
  const grandTotal = totals.reduce((a, b) => a + b.total, 0) || 1;
  const avgPct = totals.length > 0 ? 100 / totals.length : 0;
  const thisTotal = totals.find((t) => t.sector === sector)?.total ?? 0;
  const pct = (thisTotal / grandTotal) * 100;
  const diff = pct - avgPct;
  const colorClass = diff > 5 ? "text-destructive" : diff > 0 ? "text-primary" : "text-muted-foreground";
  return { text: `${diff >= 0 ? "+" : ""}${diff.toFixed(1)}% vs avg`, colorClass };
}

export function taConfidenceColor(conf: number | null): string {
  if (conf === null) return "text-muted-foreground";
  if (conf >= 80) return "text-success";
  if (conf >= 50) return "text-primary";
  return "text-destructive";
}

export function cvssColorClass(score: number | null | undefined): string {
  const v = score ?? 0;
  if (v >= 9) return "text-destructive";
  if (v >= 7) return "text-warning";
  if (v >= 4) return "text-primary";
  return "text-muted-foreground";
}

function csvRow(cells: (string | number | null | undefined)[]): string {
  return cells.map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",");
}

/** Port `exportExecCsv()` (`exec.js:687-728`). */
export function buildExecCsv(d: import("@/lib/api/loose-types").ExecDashboardV2): string {
  const prevSet = new Set(d.prev_ta_names.map((n) => n.toLowerCase()));
  const rows: string[] = [
    csvRow(["=== SECTOR RISK MATRIX ==="]),
    csvRow(["Sector", "Risk Score"]),
    ...d.sector_risk_scores.map((r) => csvRow([r.sector, r.risk_score])),
    "",
    csvRow(["=== TOP THREAT ACTORS ==="]),
    csvRow(["Threat Actor", "Incident Count", "Status"]),
    ...d.ta_leaderboard.map((ta) => csvRow([ta.name, ta.count, !d.prev_period_reliable ? "n/a" : prevSet.has(ta.name.toLowerCase()) ? "RECURRING" : "NEW"])),
    "",
    csvRow(["=== CVE EXPOSURE ==="]),
    csvRow(["Technology", "Total", "Critical", "High", "Medium", "Max CVSS", "PoC Count"]),
    ...d.cve_exposure_v2.map((r) => csvRow([r.tech, r.total, r.critical, r.high, r.medium, r.max_cvss, r.poc_count])),
    "",
    csvRow(["=== SPIKE ALERTS ==="]),
    csvRow(["Sector/Industry", "Date", "Count", "Z-Score", "Severity"]),
    ...d.industry_spikes.map((sp) => csvRow([sp.entity, sp.date, sp.count, sp.z_score, sp.severity])),
    "",
    csvRow(["=== KPI SUMMARY ==="]),
    csvRow(["Metric", "Value"]),
    csvRow(["Total Incidents", d.total_incidents]),
    csvRow(["Active Sectors", d.active_sectors ?? d.top_sectors.length]),
    csvRow(["Unique Threat Actors", d.unique_ta_count ?? d.ta_leaderboard.length]),
    csvRow(["Critical CVEs", d.cve_kpis.critical]),
    csvRow(["KEV CVEs", d.cve_kpis.kev]),
    csvRow(["Highest Risk Sector", d.sector_risk_scores[0]?.sector ?? ""]),
    csvRow(["Highest Risk Score", d.sector_risk_scores[0]?.risk_score ?? 0]),
    csvRow(["Active Spikes", d.industry_spikes.length]),
  ];
  return rows.join("\n");
}

export function downloadExecCsv(d: import("@/lib/api/loose-types").ExecDashboardV2): void {
  const csv = buildExecCsv(d);
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `cti-exec-dashboard-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
