import { priorityTone } from "@/components/newsroom/score-reasons";

// Peta literal: Tailwind tidak bisa melihat nama kelas yang dirakit saat runtime.
const TONE_CLASS = {
  destructive: "bg-destructive/15 text-destructive-text",
  warning: "bg-warning/15 text-warning-text",
  info: "bg-info/15 text-info-text",
} as const;

/** Chip "PRIORITY {skor}" (angka mentah, C25), diwarnai `priorityTone`. Tidak interaktif. */
export function PriorityChip({ score }: { score: number }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full px-1.5 text-2xs font-semibold leading-4 ${TONE_CLASS[priorityTone(score)]}`}
    >
      PRIORITY {score}
    </span>
  );
}
