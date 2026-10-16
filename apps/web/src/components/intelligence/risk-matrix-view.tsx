"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { RiskMatrixResponse } from "@/lib/api/loose-types";

function riskTierClass(score: number): { bg: string; text: string } {
  if (score <= 25) return { bg: "bg-success/20", text: "text-success-text" };
  if (score <= 50) return { bg: "bg-info/20", text: "text-info-text" };
  if (score <= 75) return { bg: "bg-warning/25", text: "text-warning-text" };
  return { bg: "bg-severity-critical/25", text: "text-severity-critical-text" };
}

/** Port `risk_matrix.js` (90 baris) -- matriks Industry × Country, skor
 * 0-100 dari unique-TA/unique-TTP/volume periode berjalan vs
 * sebelumnya. Tier warna 4 tingkat legacy (`_rmCellColor`/
 * `_rmCellTextColor`, literal rgba) di-mapping ke token Tailwind
 * (success/primary/warning/destructive), konsisten sama re-theme Fase
 * 8. `min_score` filter murni client-side, port apa adanya. */
export function RiskMatrixView() {
  const [days, setDays] = useState(30);
  const [compareDays, setCompareDays] = useState(30);
  const [minScore, setMinScore] = useState(0);

  const query = useQuery({
    queryKey: ["intelligence", "risk-matrix", days, compareDays],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/intelligence/risk-matrix", {
        params: { query: { days, compare_days: compareDays } },
      });
      if (error) throw error;
      return data as unknown as RiskMatrixResponse;
    },
  });

  const d = query.data;
  const filtered = d ? d.matrix.filter((r) => r.risk_score >= minScore) : [];
  const visIndustries = d ? d.industries.filter((ind) => filtered.some((r) => r.industry === ind)) : [];
  const visCountries = d ? d.countries.filter((cty) => filtered.some((r) => r.country === cty)) : [];
  const cellMap = new Map(filtered.map((r) => [`${r.industry}||${r.country}`, r]));

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Period (days)</Label>
          <Input
            type="number" aria-label="Period (days)"
            min={7}
            max={90}
            value={days}
            onChange={(e) => setDays(Number(e.target.value) || 30)}
            className="w-24 font-mono text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Compare period (days)</Label>
          <Input
            type="number" aria-label="Compare period (days)"
            min={7}
            max={90}
            value={compareDays}
            onChange={(e) => setCompareDays(Number(e.target.value) || 30)}
            className="w-24 font-mono text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Min risk score</Label>
          <Input
            type="number" aria-label="Min risk score"
            min={0}
            max={100}
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value) || 0)}
            className="w-24 font-mono text-xs"
          />
        </div>
      </div>

      {query.isPending && (
        <p className="py-8 text-center font-mono text-xs text-muted-foreground">Computing risk matrix…</p>
      )}
      {query.isError && <p className="py-8 text-center text-xs text-destructive">Failed to load risk matrix.</p>}

      {d && (
        <>
          <p className="mb-3 font-mono text-xs text-muted-foreground">
            Generated {d.generated_at} — {filtered.length} cells across {visIndustries.length} industries ×{" "}
            {visCountries.length} countries
          </p>
          {filtered.length === 0 ? (
            <p className="py-8 text-center font-mono text-xs text-muted-foreground">
              No cells meet the minimum risk score filter.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-2xl surface-raised p-4">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr>
                    <th className="border border-border bg-surface px-2 py-1.5 text-muted-foreground">
                      Industry \ Country
                    </th>
                    {visCountries.map((cty) => (
                      <th
                        key={cty}
                        className="border border-border bg-surface px-2 py-1.5 whitespace-nowrap text-muted-foreground"
                        title={cty}
                      >
                        {cty.length > 12 ? cty.slice(0, 11) + "…" : cty}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {visIndustries.map((ind) => (
                    <tr key={ind}>
                      <td
                        className="max-w-[160px] truncate border border-border bg-surface px-2 py-1 whitespace-nowrap text-foreground"
                        title={ind}
                      >
                        {ind}
                      </td>
                      {visCountries.map((cty) => {
                        const cell = cellMap.get(`${ind}||${cty}`);
                        if (!cell) return <td key={cty} className="min-w-[48px] border border-border bg-surface" />;
                        const tier = riskTierClass(cell.risk_score);
                        const actors = cell.top_actors.length ? cell.top_actors.join(", ") : "—";
                        return (
                          <td
                            key={cty}
                            className={cn("min-w-[48px] border border-border px-1.5 py-1 text-center font-mono text-[13px] font-bold", tier.bg, tier.text)}
                            title={`${ind} × ${cty}\nRisk: ${cell.risk_score} ${cell.trend}\nNow: ${cell.current_count} articles | Prev: ${cell.previous_count}\nTop actors: ${actors}`}
                          >
                            {cell.risk_score}
                            {cell.trend}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
