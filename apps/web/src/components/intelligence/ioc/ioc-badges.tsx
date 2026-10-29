import { actionabilityStyle, confidenceStyle, iocTypeStyle } from "@/lib/intelligence/ioc-style";

function Chip({ label, bg, border, color }: { label: string; bg: string; border: string; color: string }) {
  return (
    <span
      className="rounded-full border px-1.5 py-0.5 font-mono text-xs"
      style={{ background: bg, borderColor: border, color }}
    >
      {label}
    </span>
  );
}

export function IocTypeBadge({ type }: { type: string }) {
  const s = iocTypeStyle(type);
  return <Chip label={s.label} bg={s.bg} border={s.border} color={s.color} />;
}

export function IocActionabilityChip({ label }: { label: string | null }) {
  if (!label) return null;
  const s = actionabilityStyle(label);
  return <Chip label={s.label} bg={s.bg} border={s.border} color={s.color} />;
}

export function IocConfidenceChip({ score }: { score: number | null }) {
  if (score == null) return null;
  const s = confidenceStyle(score);
  return <Chip label={String(score)} bg={s.bg} border={s.border} color={s.color} />;
}

const STATE_CLASS: Record<string, string> = {
  active: "border-success/35 bg-success/10 text-success-text",
  expired: "border-border bg-surface text-muted-foreground",
  revoked: "border-destructive/35 bg-destructive/10 text-destructive-text",
  allowlisted: "border-warning/40 bg-warning/10 text-warning-text",
};

export function IocStateBadge({ state }: { state: string }) {
  return (
    <span className={`rounded-full border px-1.5 py-0.5 text-xs ${STATE_CLASS[state] ?? STATE_CLASS.expired}`}>
      {state}
    </span>
  );
}

export function IocTlpChip({ tlp }: { tlp: string }) {
  return (
    <span className="rounded-full border border-border bg-surface px-1.5 py-0.5 font-code text-xs text-muted-foreground">
      TLP:{tlp.toUpperCase()}
    </span>
  );
}
