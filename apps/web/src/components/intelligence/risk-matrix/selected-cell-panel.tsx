"use client";

import Link from "next/link";
import { ArrowDownIcon, ArrowRightIcon, ArrowUpIcon } from "lucide-react";

import { EntityChip } from "@/components/entities/entity-chip";
import { Chip } from "@/components/ui/chip";
import { heroLinkClass, HeroPanel } from "@/components/ui/hero-panel";
import { countryName } from "@/lib/countries";
import { nameChip, nameChips } from "@/lib/entities/name-chips";
import type { RiskMatrixCell } from "@/lib/api/loose-types";
import { newsroomHref } from "@/lib/newsroom/links";

import { changeText, pairLabel, periodFrom, trendOf } from "./model";

const TREND_ICON = { rising: ArrowUpIcon, falling: ArrowDownIcon, stable: ArrowRightIcon } as const;

// Teks dari `services/risk_matrix.py` (C9): ubah bersama rumus skornya.
const HOW_IT_WORKS =
  "3 × unique threat actors + 2 × unique ATT&CK techniques + articles in this period, scaled so the hottest cell is 100. Cells need at least 2 articles. The arrow rises when articles grow by more than 20 % and falls when they drop by more than 20 %.";

interface SelectedCellPanelProps {
  cell: RiskMatrixCell;
  hottest: boolean;
  days: number;
  generatedAt: string;
}

/** Panel "Selected cell" (HeroPanel). Tautan Newsroom memakai `from` = batas bawah jendela matriks, jadi
 * jumlah artikel di sheet sama dengan "This period". */
export function SelectedCellPanel({ cell, hottest, days, generatedAt }: SelectedCellPanelProps) {
  const trend = trendOf(cell);
  const Arrow = TREND_ICON[trend];
  const href = newsroomHref({
    industry: cell.industry,
    country: cell.country,
    from: periodFrom(generatedAt, days),
  });

  return (
    <HeroPanel
      kicker="Selected cell"
      title={pairLabel(cell)}
      footer={
        <>
          <Link href={href} className={heroLinkClass}>
            Open in Newsroom
          </Link>
          <EntityChip type="identity" name={cell.industry} />
          <EntityChip {...nameChip("location", cell.country)} label={countryName(cell.country)} />
        </>
      }
    >
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-heading text-5xl leading-none font-bold text-hero-foreground tabular-nums">
          {cell.risk_score}
        </span>
        <Chip kind="risk" value={cell.risk_score} />
        <Arrow role="img" aria-label={trend} className="size-4 text-hero-foreground" />
        {hottest && <span className="text-xs">hottest cell in the matrix</span>}
      </div>

      <dl className="mt-3 grid grid-cols-3 gap-3">
        {(
          [
            ["This period", cell.current_count],
            ["Compare period", cell.previous_count],
            ["Change", changeText(cell)],
          ] as const
        ).map(([label, value]) => (
          <div key={label}>
            <dt className="text-2xs">{label}</dt>
            <dd className="font-heading text-lg font-semibold text-hero-foreground tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-3">
        <h3 className="mb-1.5 text-2xs font-bold tracking-[0.12em] text-hero-eyebrow uppercase">
          Top actors in this cell
        </h3>
        {cell.top_actors.length ? (
          <ul className="flex flex-wrap gap-1.5">
            {nameChips("intrusion-set", cell.top_actors).map((a) => (
              <li key={a.name} className="min-w-0">
                <EntityChip {...a} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs">No named actors in this period.</p>
        )}
      </div>

      <div className="mt-3">
        <h3 className="mb-1 text-2xs font-bold tracking-[0.12em] text-hero-eyebrow uppercase">
          How the score works
        </h3>
        <p className="text-xs">{HOW_IT_WORKS}</p>
      </div>

      <p className="mt-3 text-2xs">Opens Newsroom with the same industry, country and period</p>
    </HeroPanel>
  );
}
