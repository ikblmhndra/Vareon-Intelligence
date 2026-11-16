import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

// Kelas ditulis utuh supaya Tailwind menemukannya.
const FILL = {
  neutral: "bg-foreground",
  primary: "bg-primary",
  destructive: "bg-destructive",
  warning: "bg-warning",
  success: "bg-success",
} as const;

interface MeterBarProps {
  value: number;
  max: number;
  tone?: keyof typeof FILL;
  /** `baseline`: penanda tick di `baseline`; `diverging`: nol di tengah, positif merah, negatif hijau. */
  variant?: "default" | "baseline" | "diverging";
  baseline?: number;
  label?: ReactNode;
  /** Di atas `HeroPanel` (burgundy tetap): jalur, isi, dan tick memakai token `hero-*` yang kontras di kedua tema. */
  onHero?: boolean;
  "aria-label": string;
  className?: string;
}

const clampPct = (n: number) => Math.min(100, Math.max(0, n));

/** Batang meter horizontal (`role="meter"`). Nilai dibaca pembaca layar lewat `aria-valuenow/min/max` dan
 * `aria-valuetext`; slot `label` hanya tampilan. `max <= 0` dianggap kosong, bukan membagi nol. */
export function MeterBar({
  value,
  max,
  tone = "neutral",
  variant = "default",
  baseline,
  label,
  onHero,
  "aria-label": ariaLabel,
  className,
}: MeterBarProps) {
  const diverging = variant === "diverging";
  const min = diverging ? -max : 0;
  const span = max > 0 ? (diverging ? 2 * max : max) : 1;
  const text =
    variant === "baseline" && baseline !== undefined
      ? `${value} of ${max}, baseline ${baseline}`
      : `${value} of ${max}`;

  let fillStyle: { left: string; width: string };
  let fillClass: string = onHero ? "bg-hero-accent" : FILL[tone];
  if (diverging) {
    const v = Math.min(max, Math.max(-max, value));
    const half = max > 0 ? (Math.abs(v) / max) * 50 : 0;
    fillStyle = v >= 0 ? { left: "50%", width: `${half}%` } : { left: `${50 - half}%`, width: `${half}%` };
    fillClass = v >= 0 ? FILL.destructive : FILL.success;
  } else {
    fillStyle = { left: "0%", width: `${clampPct((value / span) * 100)}%` };
  }

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div
        role="meter"
        aria-label={ariaLabel}
        aria-valuenow={value}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuetext={text}
        className={cn("relative h-2 min-w-16 flex-1 overflow-hidden rounded-full", onHero ? "bg-hero-foreground/20" : "bg-surface")}
      >
        <span aria-hidden="true" className={cn("absolute inset-y-0 rounded-full", fillClass)} style={fillStyle} />
        {diverging && (
          <span aria-hidden="true" className="absolute inset-y-0 left-1/2 w-px bg-border" />
        )}
        {variant === "baseline" && baseline !== undefined && (
          <span
            aria-hidden="true"
            className={cn("absolute inset-y-0 w-0.5", onHero ? "bg-hero-foreground" : "bg-foreground")}
            style={{ left: `${clampPct((baseline / span) * 100)}%` }}
          />
        )}
      </div>
      {label && <span className="shrink-0 text-xs text-muted-foreground">{label}</span>}
    </div>
  );
}
