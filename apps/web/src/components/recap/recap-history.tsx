import { cn } from "@/lib/utils";
import type { RecapKind, RecapListItem } from "@/lib/api/loose-types";
import { formatRange } from "@/lib/recap/period";

interface RecapHistoryProps {
  items: RecapListItem[];
  /** Recap yang sedang tampil; `kind` ikut menentukan karena mingguan dan harian boleh berbagi tanggal. */
  selected: { kind: RecapKind; date: string } | null;
  onSelect: (item: RecapListItem) => void;
}

/** Port sidebar `#recap-history-list` di `recapLoadHistory()` lama; kini memuat dua jenis recap. */
export function RecapHistory({ items, selected, onSelect }: RecapHistoryProps) {
  if (!items.length) {
    return <p className="p-1.5 text-xs text-muted-foreground">No recaps yet.</p>;
  }

  return (
    <div className="flex flex-col gap-1">
      {items.map((it) => {
        const c = it.counts || {};
        const active = it.kind === selected?.kind && it.date === selected?.date;
        const weekly = it.kind === "weekly";
        return (
          <button
            key={`${it.kind}:${it.date}`}
            onClick={() => onSelect(it)}
            className={cn(
              "rounded-md border px-2 py-1.5 text-left font-mono text-[13px] transition-colors",
              active
                ? "border-primary/50 bg-primary/10"
                : "border-border hover:bg-accent",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className={active ? "text-primary-text" : "text-foreground"}>
                {weekly ? formatRange(it.period_start, it.period_end) : it.date}
              </span>
              <span className="text-[11px] tracking-wide text-muted-foreground uppercase">
                {weekly ? "week" : "day"}
              </span>
            </div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              {c.articles ?? 0}a · {c.tweets ?? 0}t · {c.cves ?? 0}c
            </div>
          </button>
        );
      })}
    </div>
  );
}
