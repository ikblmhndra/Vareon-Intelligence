"use client";

import { ArrowDownIcon, ArrowRightIcon, ArrowUpIcon } from "lucide-react";

import { EntityChip } from "@/components/entities/entity-chip";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { MeterBar } from "@/components/ui/meter-bar";
import { nameChip } from "@/lib/entities/name-chips";
import type { RiskMatrixCell } from "@/lib/api/loose-types";
import { cn } from "@/lib/utils";

import { cellKey, pairLabel, trendOf } from "./model";

const TREND_ICON = { rising: ArrowUpIcon, falling: ArrowDownIcon, stable: ArrowRightIcon } as const;

const TOP_N = 8;
/** Syarat "movers": pembanding minimal 3 artikel supaya lonjakan dari 1 -> 4 tak mendominasi daftar. */
const MOVER_MIN_PREVIOUS = 3;

function CardTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div>
      <h2 className="font-heading text-base font-semibold">{title}</h2>
      <p className="text-xs text-muted-foreground">{subtitle}</p>
    </div>
  );
}

interface PairsCardProps {
  cells: RiskMatrixCell[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  /** `null` = pengguna tanpa `export_data`: tombol tidak dirender. */
  onExport: (() => void) | null;
}

/** "Highest-risk pairs": 8 sel teratas. Klik baris memilih sel; tombol di sel pertama membuat baris dapat
 * dijangkau papan-ketik, dan chip aktor (tautan) ada di sel terpisah supaya tak bersarang di tombol. */
export function PairsCard({ cells, selectedKey, onSelect, onExport }: PairsCardProps) {
  const top = [...cells].sort((a, b) => b.risk_score - a.risk_score).slice(0, TOP_N);
  return (
    <Card>
      <div className="flex flex-col gap-3 px-5">
        <div className="flex items-start justify-between gap-3">
          <CardTitle title="Highest-risk pairs" subtitle={`Top ${TOP_N} cells by score`} />
          {onExport && (
            <Button variant="outline" size="sm" onClick={onExport}>
              Export CSV
            </Button>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-2xs font-semibold tracking-wide text-muted-foreground uppercase">
                <th scope="col" className="w-8 py-1.5 font-semibold">
                  #
                </th>
                <th scope="col" className="py-1.5 font-semibold">
                  Industry × country
                </th>
                <th scope="col" className="py-1.5 font-semibold">
                  Score
                </th>
                <th scope="col" className="py-1.5 font-semibold">
                  Articles
                </th>
                <th scope="col" className="py-1.5 font-semibold">
                  Top actor
                </th>
              </tr>
            </thead>
            <tbody>
              {top.map((c, i) => {
                const key = cellKey(c);
                const Arrow = TREND_ICON[trendOf(c)];
                const selected = key === selectedKey;
                return (
                  <tr
                    key={key}
                    aria-selected={selected}
                    onClick={() => onSelect(key)}
                    className={cn("cursor-pointer border-t border-border", selected && "bg-surface")}
                  >
                    <td className="py-2 tabular-nums text-muted-foreground">{i + 1}</td>
                    <td className="py-2 pr-2">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelect(key);
                        }}
                        className="rounded-sm text-left font-medium outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                      >
                        {pairLabel(c)}
                      </button>
                    </td>
                    <td className="py-2 pr-2">
                      <span className="inline-flex items-center gap-1">
                        <Chip kind="risk" value={c.risk_score}>
                          {c.risk_score}
                        </Chip>
                        <Arrow role="img" aria-label={trendOf(c)} className="size-3 text-muted-foreground" />
                      </span>
                    </td>
                    <td className="py-2 pr-2 tabular-nums">
                      {c.current_count} / {c.previous_count}
                    </td>
                    <td className="py-2" onClick={(e) => e.stopPropagation()}>
                      {c.top_actors[0] ? (
                        <EntityChip {...nameChip("intrusion-set", c.top_actors[0])} className="max-w-40" />
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-2xs text-muted-foreground">
          Articles shown as this period / compare period. Export CSV includes every cell.
        </p>
      </div>
    </Card>
  );
}

/** "Biggest movers": selisih jumlah artikel terbesar (nilai mutlak) di antara sel yang pembandingnya >= 3. */
export function MoversCard({ cells }: { cells: RiskMatrixCell[] }) {
  const movers = cells
    .filter((c) => c.previous_count >= MOVER_MIN_PREVIOUS)
    .map((c) => ({ c, delta: c.current_count - c.previous_count }))
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
    .slice(0, TOP_N);
  const max = Math.max(1, ...movers.map((m) => Math.abs(m.delta)));
  return (
    <Card>
      <div className="flex flex-col gap-3 px-5">
        <CardTitle title="Biggest movers" subtitle="Largest change in articles vs the compare period" />
        {movers.length === 0 ? (
          <p className="py-4 text-sm text-muted-foreground">No pair has enough articles in the compare period.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {movers.map(({ c, delta }) => (
              <li key={cellKey(c)} className="flex flex-col gap-1">
                <p className="text-xs">
                  <span className="font-medium">{pairLabel(c)}</span>{" "}
                  <span className="text-muted-foreground tabular-nums">
                    {c.previous_count} → {c.current_count}
                  </span>
                </p>
                <MeterBar
                  variant="diverging"
                  value={delta}
                  max={max}
                  aria-label={`${pairLabel(c)}: ${c.previous_count} to ${c.current_count} articles`}
                  label={
                    <span
                      className={cn(
                        "tabular-nums",
                        delta > 0 ? "text-destructive-text" : delta < 0 ? "text-success-text" : undefined,
                      )}
                    >
                      {delta > 0 ? "+" : ""}
                      {delta}
                    </span>
                  }
                />
              </li>
            ))}
          </ul>
        )}
        <p className="text-2xs text-muted-foreground">Only pairs with at least 3 articles in the compare period.</p>
      </div>
    </Card>
  );
}
