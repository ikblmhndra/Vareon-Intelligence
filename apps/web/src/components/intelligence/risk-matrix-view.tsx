"use client";

import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { MoversCard, PairsCard } from "@/components/intelligence/risk-matrix/pairs-and-movers";
import { SelectedCellPanel } from "@/components/intelligence/risk-matrix/selected-cell-panel";
import {
  cellKey,
  pairLabel,
  tierOf,
  trendOf,
} from "@/components/intelligence/risk-matrix/model";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { HeatCell, HeatGrid } from "@/components/ui/heat-grid";
import { Input } from "@/components/ui/input";
import { LegendRow } from "@/components/ui/legend-row";
import { PresetControl } from "@/components/ui/preset-control";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatePanel } from "@/components/ui/state-panel";
import { api } from "@/lib/api/client";
import type { RiskMatrixCell, RiskMatrixResponse } from "@/lib/api/loose-types";
import { useCan } from "@/lib/auth/permissions";
import { countryName } from "@/lib/countries";
import { downloadCsv, toCsv } from "@/lib/csv";
import { fmtTime } from "@/lib/format";

const PERIODS = [
  { value: 7, label: "7d" },
  { value: 30, label: "30d" },
  { value: 60, label: "60d" },
  { value: 90, label: "90d" },
] as const;

const MIN_SCORES = [
  { value: 0, label: "All" },
  { value: 25, label: "≥25" },
  { value: 50, label: "≥50" },
  { value: 75, label: "≥75" },
] as const;

const COMPARE_PRESETS = [7, 14, 30, 60, 90] as const;
const COMPARE_ITEMS: Record<string, string> = {
  ...Object.fromEntries(COMPARE_PRESETS.map((n) => [String(n), `Previous ${n} days`])),
  custom: "Custom…",
};

const LEGEND = [
  { label: "Low", swatchClass: "bg-success/15" },
  { label: "Med", swatchClass: "bg-warning/20" },
  { label: "High", swatchClass: "bg-destructive/20" },
] as const;

/** COMPARE WITH: pilihan "Previous N days" + "Custom…" (7-90, batas API) yang membuka input angka. Angka di
 * luar rentang hanya menampilkan galat dan nilai lama dipertahankan, jadi query tak pernah ditolak backend. */
function CompareControl({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  const id = useId();
  const [custom, setCustom] = useState(false);
  const [draft, setDraft] = useState(String(value));
  const [error, setError] = useState<string>();
  const isCustom = custom || !(COMPARE_PRESETS as readonly number[]).includes(value);

  function commit() {
    const n = draft.trim() === "" ? Number.NaN : Number(draft);
    if (!Number.isInteger(n) || n < 7 || n > 90) {
      setError("Enter a whole number from 7 to 90.");
      return;
    }
    setError(undefined);
    onChange(n);
  }

  return (
    <div className="flex flex-col gap-1">
      <span className="text-2xs font-semibold tracking-wide text-muted-foreground uppercase">Compare with</span>
      <div className="flex flex-wrap items-start gap-2">
        <Select
          items={COMPARE_ITEMS}
          value={isCustom ? "custom" : String(value)}
          onValueChange={(v) => {
            if (v == null) return;
            setError(undefined);
            if (v === "custom") {
              setDraft(String(value));
              setCustom(true);
            } else {
              setCustom(false);
              onChange(Number(v));
            }
          }}
        >
          <SelectTrigger aria-label="Compare with" size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(COMPARE_ITEMS).map(([v, label]) => (
              <SelectItem key={v} value={v}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {isCustom && (
          <Field
            label="Compare with (custom days)"
            htmlFor={`${id}-custom`}
            error={error}
            className="w-28 gap-1 [&>label]:sr-only"
          >
            <Input
              id={`${id}-custom`}
              type="number"
              min={7}
              max={90}
              step={1}
              value={draft}
              aria-invalid={!!error}
              aria-describedby={fieldDescribedBy(`${id}-custom`, { error })}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commit();
                }
              }}
              className="h-8 text-xs"
            />
          </Field>
        )}
      </div>
    </div>
  );
}

/** Risk Matrix (spec 2b 6.1): grid industri × negara (HeatGrid, navigasi panah), panel sel terpilih, pasangan
 * berisiko tertinggi dan mover terbesar. Skor 0-100 dari unique-TA/unique-TTP/volume periode berjalan vs
 * pembanding (`services/risk_matrix.py`). Filter `min_score` murni sisi klien: sel di bawah ambang jadi kotak
 * kosong supaya bentuk grid tetap. */
export function RiskMatrixView() {
  const can = useCan();
  const [days, setDays] = useState(30);
  const [compareDays, setCompareDays] = useState(30);
  const [minScore, setMinScore] = useState(0);
  // Disimpan sebagai kunci; bila sel hilang (periode berubah) jatuh ke sel terpanas yang terlihat.
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

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
  const visible = d ? d.matrix.filter((r) => r.risk_score >= minScore) : [];
  const cellMap = new Map<string, RiskMatrixCell>(visible.map((r) => [cellKey(r), r]));
  const hottest = d?.matrix.reduce<RiskMatrixCell | null>(
    (best, r) => (best === null || r.risk_score > best.risk_score ? r : best),
    null,
  );
  const hottestVisible = visible.reduce<RiskMatrixCell | null>(
    (best, r) => (best === null || r.risk_score > best.risk_score ? r : best),
    null,
  );
  // Panel memakai seluruh matriks: baris "Highest-risk pairs" di bawah ambang tetap bisa dipilih (selnya
  // kosong di grid, tapi panelnya tetap jujur). Tanpa pilihan, jatuh ke sel terpanas yang terlihat.
  const allMap = new Map<string, RiskMatrixCell>((d?.matrix ?? []).map((r) => [cellKey(r), r]));
  const selected = (selectedKey ? allMap.get(selectedKey) : undefined) ?? hottestVisible;

  function exportCsv() {
    if (!d) return;
    const rows = d.matrix.map((c) => [
      c.industry,
      c.country,
      c.risk_score,
      trendOf(c),
      c.current_count,
      c.previous_count,
      c.top_actors,
    ]);
    downloadCsv(
      `risk-matrix-${days}d-vs-${compareDays}d.csv`,
      toCsv(["industry", "country", "risk_score", "trend", "current_count", "previous_count", "top_actors"], rows),
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          <PresetControl
            label="Period"
            aria-label="Period days"
            presets={PERIODS}
            value={days}
            onChange={setDays}
            min={7}
            max={90}
          />
          <CompareControl value={compareDays} onChange={setCompareDays} />
          <PresetControl
            label="Min risk score"
            aria-label="Minimum risk score"
            presets={MIN_SCORES}
            value={minScore}
            onChange={setMinScore}
            min={0}
            max={100}
          />
        </div>
        {d && (
          <p className="text-xs text-muted-foreground">
            Generated {fmtTime(d.generated_at)} · {d.matrix.length} cells · {d.industries.length} industries ×{" "}
            {d.countries.length} countries
          </p>
        )}
      </div>

      {query.isPending && (
        <StatePanel variant="loading" title="Computing risk matrix" description="Scoring every industry and country pair." />
      )}
      {query.isError && (
        <StatePanel
          variant="error"
          title="Could not load the risk matrix"
          action={
            <Button variant="outline" size="sm" onClick={() => query.refetch()}>
              Retry
            </Button>
          }
        />
      )}

      {d && d.matrix.length === 0 && (
        <StatePanel
          variant="empty"
          title="No risk cells in this period"
          description="A cell needs at least 2 articles in the period for one industry and country."
        />
      )}

      {d && d.matrix.length > 0 && (
        <>
          <div className="grid items-start gap-4 lg:grid-cols-5">
            <Card className="lg:col-span-3">
              <div className="flex flex-col gap-3 px-5">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <h2 className="font-heading text-base font-semibold">Industry × country</h2>
                    <p className="text-xs text-muted-foreground">
                      Score 0-100, relative to the hottest cell; arrow = change vs the compare period
                    </p>
                  </div>
                  <LegendRow items={LEGEND} />
                </div>
                {visible.length === 0 && (
                  <p className="text-xs text-muted-foreground">No cells meet the minimum risk score.</p>
                )}
                <HeatGrid
                  aria-label="Risk score by industry and country"
                  rowLabels={d.industries}
                  colLabels={d.countries.map((c) => (
                    <span key={c} className="block max-w-24 truncate" title={countryName(c)}>
                      {countryName(c)}
                    </span>
                  ))}
                  active={
                    selected
                      ? [d.industries.indexOf(selected.industry), d.countries.indexOf(selected.country)]
                      : null
                  }
                  onSelect={(r, c) => {
                    const cell = cellMap.get(`${d.industries[r]}||${d.countries[c]}`);
                    if (cell) setSelectedKey(cellKey(cell));
                  }}
                  renderCell={(r, c) => {
                    const ind = d.industries[r];
                    const cty = d.countries[c];
                    const cell = cellMap.get(`${ind}||${cty}`);
                    if (!cell) {
                      return (
                        <HeatCell
                          variant="tier"
                          value={null}
                          aria-label={`${ind} × ${countryName(cty)}, no score`}
                        />
                      );
                    }
                    const tier = tierOf(cell.risk_score);
                    const trend = trendOf(cell);
                    const actors = cell.top_actors.length ? cell.top_actors.join(", ") : "—";
                    return (
                      <HeatCell
                        variant="tier"
                        value={cell.risk_score}
                        tier={tier}
                        trend={trend}
                        outlined={cell === hottest}
                        selected={selected ? cellKey(selected) === cellKey(cell) : false}
                        aria-label={`${pairLabel(cell)}, score ${cell.risk_score}, ${tier === "med" ? "medium" : tier}, ${trend}`}
                        title={`${pairLabel(cell)}\nRisk: ${cell.risk_score} ${cell.trend}\nNow: ${cell.current_count} articles | Prev: ${cell.previous_count}\nTop actors: ${actors}`}
                      />
                    );
                  }}
                />
              </div>
            </Card>
            <div className="lg:col-span-2">
              {selected ? (
                <SelectedCellPanel
                  cell={selected}
                  hottest={selected === hottest}
                  days={days}
                  generatedAt={d.generated_at}
                />
              ) : (
                <StatePanel
                  variant="empty"
                  title="No cell selected"
                  description="No cell meets the minimum risk score. Lower it to select one."
                />
              )}
            </div>
          </div>

          <div className="grid items-start gap-4 lg:grid-cols-2">
            <PairsCard
              cells={d.matrix}
              selectedKey={selected ? cellKey(selected) : null}
              onSelect={setSelectedKey}
              onExport={can("export_data") ? exportCsv : null}
            />
            <MoversCard cells={d.matrix} />
          </div>
        </>
      )}
    </div>
  );
}
