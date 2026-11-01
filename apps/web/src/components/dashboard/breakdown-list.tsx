import { EntityChip, type EntityChipItem } from "@/components/entities/entity-chip";

interface BreakdownItem {
  label: string;
  count: number;
  /** Bila ada, label tampil sebagai chip entity (tautan ke halaman entity). */
  chip?: EntityChipItem;
}

/** Daftar proporsi (label + batang + angka); pengganti donut saat kategorinya banyak. */
export function BreakdownList({ items, limit = 8 }: { items: BreakdownItem[]; limit?: number }) {
  const shown = items.slice(0, limit);
  const max = Math.max(1, ...shown.map((i) => i.count));
  return (
    <ul className="flex flex-col gap-3.5">
      {shown.map((i) => (
        <li key={i.label} className="flex flex-col gap-1.5">
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate text-foreground">
              {i.chip ? <EntityChip {...i.chip} label={i.label} /> : i.label}
            </span>
            <span className="shrink-0 font-semibold text-muted-foreground tabular-nums">{i.count.toLocaleString()}</span>
          </div>
          <div className="h-2.5 rounded-full bg-background">
            <div className="h-2.5 rounded-full bg-chart-1" style={{ width: `${(i.count / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
