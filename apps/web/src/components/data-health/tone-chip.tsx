import type { ReactNode } from "react";

import { Chip } from "@/components/ui/chip";
import { TONE_LABEL, type Tone } from "@/lib/data-health/tones";

/** Chip satu-satunya untuk nada Data health; teks bawaan `TONE_LABEL`. "OFF" dan UNKNOWN memakai `flag`. */
export function ToneChip({ tone, children }: { tone: Tone; children?: ReactNode }) {
  const text = children ?? TONE_LABEL[tone];
  switch (tone) {
    case "ok":
      return <Chip kind="status" value="ok">{text}</Chip>;
    case "warn":
      return <Chip kind="status" value="watch">{text}</Chip>;
    case "bad":
      return <Chip kind="status" value="action">{text}</Chip>;
    default:
      return <Chip kind="flag" value="unknown">{text}</Chip>;
  }
}
