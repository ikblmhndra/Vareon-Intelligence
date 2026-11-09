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
  unrated: "bg-panel text-foreground",
} as const;

const STATUS = {
  ok: "bg-success/15 text-success-text",
  watch: "bg-warning/15 text-warning-text",
  action: "bg-destructive/15 text-destructive-text",
  open: "bg-destructive/15 text-destructive-text",
  in_progress: "bg-primary/15 text-primary-text",
  completed: "bg-success/15 text-success-text",
} as const;

const RISK = {
  LOW: "bg-success/15 text-success-text",
  MED: "bg-warning/15 text-warning-text",
  HIGH: "bg-destructive/15 text-destructive-text",
} as const;

const NEUTRAL = "bg-panel text-foreground";

// Kata + tint lencana CVE Tracker (spec 2a 6.11).
const CVE = {
  kev: { word: "KEV", tone: "bg-destructive/15 text-destructive-text" },
  exploited: { word: "EXPLOITED", tone: "bg-destructive/15 text-destructive-text" },
  poc: { word: "PoC", tone: NEUTRAL },
  acknowledged: { word: "ACKNOWLEDGED", tone: "bg-success/15 text-success-text" },
  false_positive: { word: "FALSE POSITIVE", tone: NEUTRAL },
  monitored: { word: "MONITORED", tone: "bg-success/15 text-success-text" },
  covered_by_vendor: { word: "COVERED BY VENDOR", tone: "bg-info/15 text-info-text" },
  unmapped: { word: "unmapped", tone: "bg-warning/15 text-warning-text" },
  escalation: { word: "ESCALATION", tone: "bg-warning/15 text-warning-text" },
} as const;

const EXPOSURE = {
  public: { word: "public", tone: "bg-destructive/15 text-destructive-text" },
  internal: { word: "internal", tone: NEUTRAL },
  both: { word: "public + internal", tone: NEUTRAL },
} as const;

const TICKET = {
  Open: "bg-destructive/15 text-destructive-text",
  "In Progress": "bg-warning/15 text-warning-text",
  Resolved: "bg-success/15 text-success-text",
  "Risk Accepted": NEUTRAL,
  Closed: NEUTRAL,
} as const;

type ChipProps = { children?: ReactNode; className?: string } & (
  | { kind: "severity"; value: keyof typeof SEVERITY }
  | { kind: "status"; value: keyof typeof STATUS }
  | { kind: "cve"; value: keyof typeof CVE }
  | { kind: "exposure"; value: keyof typeof EXPOSURE }
  | { kind: "ticket"; value: keyof typeof TICKET }
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
    case "cve":
      tone = CVE[props.value].tone;
      text = children ?? CVE[props.value].word;
      break;
    case "exposure":
      tone = EXPOSURE[props.value].tone;
      text = children ?? EXPOSURE[props.value].word;
      break;
    case "ticket":
      tone = TICKET[props.value];
      text = children ?? props.value;
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
