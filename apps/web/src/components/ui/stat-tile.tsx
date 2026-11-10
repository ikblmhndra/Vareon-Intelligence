import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

// Kelas ditulis utuh supaya Tailwind menemukannya.
const TONE = {
  neutral: { bar: "bg-foreground", value: "text-foreground" },
  destructive: { bar: "bg-destructive", value: "text-destructive-text" },
  warning: { bar: "bg-warning", value: "text-warning-text" },
  info: { bar: "bg-info", value: "text-info-text" },
  success: { bar: "bg-success", value: "text-success-text" },
} as const;

interface StatTileProps {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: keyof typeof TONE;
  tooltip?: ReactNode;
  /** Tile terpilih (hanya bermakna bersama `onSelect`). */
  selected?: boolean;
  /** Bila ada, tile dirender sebagai `<button aria-pressed>` (filter tipe IOC). */
  onSelect?: () => void;
  className?: string;
}

/** Kotak angka ringkas: batang warna 2 px di atas, label 11 px kapital, angka besar, keterangan kecil.
 * `tooltip` (opsional) menjelaskan label saat di-hover/fokus. */
export function StatTile({ label, value, sub, tone = "neutral", tooltip, selected, onSelect, className }: StatTileProps) {
  const t = TONE[tone];
  const labelEl = (
    <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
  );
  const card = (
    <Card
      variant="tile"
      size="sm"
      className={cn("relative gap-1 px-4", onSelect && selected && "ring-2 ring-foreground", !onSelect && className)}
    >
      <span aria-hidden="true" className={cn("absolute inset-x-0 top-0 h-0.5", t.bar)} />
      {tooltip ? (
        <Tooltip>
          <TooltipTrigger render={<span tabIndex={0} className="w-fit outline-none focus-visible:ring-2 focus-visible:ring-ring" />}>
            {labelEl}
          </TooltipTrigger>
          <TooltipContent>{tooltip}</TooltipContent>
        </Tooltip>
      ) : (
        labelEl
      )}
      <p className={cn("text-[32px] font-bold leading-tight", t.value)}>{value}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </Card>
  );
  if (!onSelect) return card;
  return (
    <button
      type="button"
      aria-pressed={!!selected}
      onClick={onSelect}
      className={cn(
        "block rounded-lg text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        className,
      )}
    >
      {card}
    </button>
  );
}
