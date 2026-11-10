"use client";

import { ArrowDownIcon, ArrowRightIcon, ArrowUpIcon } from "lucide-react";
import type { ReactNode } from "react";

import { useGridRovingKeys } from "@/components/ui/use-grid-roving-keys";
import { cn } from "@/lib/utils";

// Kelas ditulis utuh supaya Tailwind menemukannya. Tint dibatasi alpha-nya (bukan membalik warna teks):
// teks tetap `text-X-text` di semua langkah, kecuali langkah 5 yang memakai band `bg-hero`.
const TIER = {
  low: "bg-success/15 text-success-text",
  med: "bg-warning/20 text-warning-text",
  high: "bg-destructive/20 text-destructive-text",
} as const;

const SCALE = [
  "bg-primary/10 text-primary-text",
  "bg-primary/20 text-primary-text",
  "bg-primary/30 text-primary-text",
  "bg-primary/40 text-primary-text",
  "bg-primary/45 text-primary-text",
  "bg-hero text-hero-foreground",
] as const;

const TREND = {
  rising: { Icon: ArrowUpIcon, label: "rising" },
  falling: { Icon: ArrowDownIcon, label: "falling" },
  stable: { Icon: ArrowRightIcon, label: "stable" },
} as const;

interface HeatCellProps {
  variant: "tier" | "scale";
  /** `null` = sel kosong (kotak berbingkai; bentuk grid tetap utuh). */
  value: number | null;
  tier?: "low" | "med" | "high";
  step?: 0 | 1 | 2 | 3 | 4 | 5;
  selected?: boolean;
  /** Penanda "sel terpanas": kontur tipis, terpisah dari cincin seleksi. */
  outlined?: boolean;
  trend?: "rising" | "falling" | "stable";
  "aria-label": string;
  title?: string;
}

/** Satu sel heatmap. Fokus dan klik ditangani pembungkus `gridcell` di `HeatGrid`; sel ini hanya menggambar
 * dan memberi nama aksesibel (`role="img"` + `aria-label`, mis. "Finance × Indonesia, score 100, high, rising"). */
export function HeatCell({
  variant,
  value,
  tier = "low",
  step = 0,
  selected,
  outlined,
  trend,
  title,
  "aria-label": ariaLabel,
}: HeatCellProps) {
  const T = trend ? TREND[trend] : null;
  return (
    <div
      role="img"
      aria-label={ariaLabel}
      title={title}
      className={cn(
        "flex h-10 min-w-10 items-center justify-center gap-1 rounded-md px-1.5 text-xs font-semibold",
        value === null
          ? "border border-border bg-background"
          : variant === "tier"
            ? TIER[tier]
            : SCALE[step],
        outlined && "outline outline-2 -outline-offset-2 outline-primary",
        selected && "ring-2 ring-inset ring-foreground",
      )}
    >
      {value !== null && (
        <>
          <span className="tabular-nums">{value}</span>
          {T && <T.Icon role="img" aria-label={T.label} className="size-3" />}
        </>
      )}
    </div>
  );
}

interface HeatGridProps {
  rowLabels: ReactNode[];
  colLabels: ReactNode[];
  renderCell: (r: number, c: number) => ReactNode;
  active: [number, number] | null;
  onSelect: (r: number, c: number) => void;
  "aria-label": string;
}

/** Grid heatmap dengan header lengket (baris atas dan kolom kiri) dan navigasi panah 2-D lewat
 * `useGridRovingKeys`. Fokus mengikuti panah tanpa memilih; Enter/Spasi/klik memilih sel. */
export function HeatGrid({
  rowLabels,
  colLabels,
  renderCell,
  active,
  onSelect,
  "aria-label": ariaLabel,
}: HeatGridProps) {
  const { onKeyDown, tabIndexFor, setRef } = useGridRovingKeys(
    rowLabels.length,
    colLabels.length,
    active,
    () => {},
    onSelect,
  );
  return (
    <div className="max-h-[32rem] overflow-auto">
      <table role="grid" aria-label={ariaLabel} onKeyDown={onKeyDown} className="border-separate border-spacing-1">
        <thead>
          <tr>
            <td className="sticky left-0 top-0 z-20 bg-background" />
            {colLabels.map((label, c) => (
              <th
                key={c}
                scope="col"
                className="sticky top-0 z-10 bg-background px-1 pb-1 text-left text-2xs font-semibold text-muted-foreground"
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rowLabels.map((label, r) => (
            <tr key={r}>
              <th
                scope="row"
                className="sticky left-0 z-10 bg-background pr-2 text-left text-xs font-medium whitespace-nowrap"
              >
                {label}
              </th>
              {colLabels.map((_, c) => (
                <td
                  key={c}
                  role="gridcell"
                  ref={setRef(r, c)}
                  tabIndex={tabIndexFor(r, c)}
                  aria-selected={active?.[0] === r && active?.[1] === c}
                  onClick={() => onSelect(r, c)}
                  className="cursor-pointer rounded-md p-0 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                >
                  {renderCell(r, c)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
