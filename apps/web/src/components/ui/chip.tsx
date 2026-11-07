import type { ReactNode } from "react";

import { RISK_HIGH_MIN, RISK_MED_MIN } from "@/lib/exec/format";
import { cn } from "@/lib/utils";

// Kelas ditulis utuh (bukan disusun) supaya Tailwind menemukannya. Pasangan tint+teks mengikuti
// aturan "text on tints" (`bg-X/15` + `text-X-text`).
const SEVERITY = {
  critical: "bg-severity-critical/15 text-severity-critical-text",
  high: "bg-severity-high/15 text-severity-high-text",
  medium: "bg-severity-medium/15 text-severity-medium-text",
  low: "bg-severity-low/15 text-severity-low-text",
} as const;

const STATUS = {
  ok: "bg-success/15 text-success-text",
  watch: "bg-warning/15 text-warning-text",
  action: "bg-destructive/15 text-destructive-text",
  open: "bg-info/15 text-info-text",
  in_progress: "bg-primary/15 text-primary-text",
  completed: "bg-success/15 text-success-text",
} as const;

const RISK = {
  LOW: "bg-success/15 text-success-text",
  MED: "bg-warning/15 text-warning-text",
  HIGH: "bg-destructive/15 text-destructive-text",
} as const;

const NEUTRAL = "bg-panel text-foreground";

type ChipProps = { children?: ReactNode; className?: string } & (
  | { kind: "severity"; value: keyof typeof SEVERITY }
  | { kind: "status"; value: keyof typeof STATUS }
  | { kind: "risk"; value: number }
  | { kind: "grade" | "flag"; value: string }
);

/** Lencana status seragam: teks = kata keadaan (huruf besar), 11 px semibold. `risk` menerima skor
 * numerik dan memetakannya ke LOW/MED/HIGH; `grade`/`flag` menampilkan `children` (atau `value`) pada tint netral. */
export function Chip(props: ChipProps) {
  const { children, className } = props;
  let tone: string;
  let text: ReactNode;
  switch (props.kind) {
    case "severity":
      tone = SEVERITY[props.value];
      text = children ?? props.value;
      break;
    case "status":
      tone = STATUS[props.value];
      text = children ?? props.value.replace("_", " ");
      break;
    case "risk": {
      const level =
        props.value >= RISK_HIGH_MIN ? "HIGH" : props.value >= RISK_MED_MIN ? "MED" : "LOW";
      tone = RISK[level];
      text = children ?? level;
      break;
    }
    default:
      tone = NEUTRAL;
      text = children ?? props.value;
  }
  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-[6px] px-2 py-0.5 text-2xs font-semibold uppercase",
        tone,
        className,
      )}
    >
      {text}
    </span>
  );
}
