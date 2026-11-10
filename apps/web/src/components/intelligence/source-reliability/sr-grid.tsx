"use client";

import { gradeChipClass, type SREntry } from "@/components/intelligence/source-reliability/sr-model";
import { Chip } from "@/components/ui/chip";
import { RowMenu } from "@/components/ui/row-menu";
import { fmtCompactAge } from "@/lib/format";
import { originLabel } from "@/lib/intelligence/format";

interface SrGridProps {
  entries: SREntry[];
  reliability: Record<string, string>;
  onOpen: (entry: SREntry) => void;
  onEdit: (entry: SREntry) => void;
  onRemove: (entry: SREntry) => void;
  canManage: boolean;
}

/** Tampilan Grid (D8): kartu per sumber, 3 kolom di `lg`, 2 di bawahnya. Badan kartu adalah satu `<button>`
 * (buka dialog); `RowMenu` diposisikan absolut di sebelahnya, bukan di dalamnya, supaya tidak ada tombol
 * bersarang. Hanya baris pertama catatan yang tampil; sisanya di dialog. */
export function SrGrid({ entries, reliability, onOpen, onEdit, onRemove, canManage }: SrGridProps) {
  return (
    <ul className="grid grid-cols-2 gap-3 px-3 pb-2 max-lg:gap-2 lg:grid-cols-3">
      {entries.map((e) => {
        const firstNote = e.notes.split("\n")[0].trim();
        return (
          <li key={e.id} className="relative rounded-xl border border-border bg-background hover:bg-surface">
            <button
              type="button"
              onClick={() => onOpen(e)}
              className="flex w-full flex-col gap-2 rounded-xl p-3 pr-11 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              <span className="flex items-center gap-2">
                <Chip kind="grade" value={e.admiralty_code} className={gradeChipClass(e.reliability_grade)} />
                <span className="truncate text-xs font-semibold">{e.source_name}</span>
              </span>
              <span className="text-xs text-muted-foreground">{reliability[e.reliability_grade] ?? "—"}</span>
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-muted-foreground">
                {e.content_kind && <Chip kind="flag" value={e.content_kind} />}
                <span>{originLabel(e.origin)}</span>
                <span>· {e.analyst_name}</span>
                <span>· {fmtCompactAge(e.last_updated || e.added_date)}</span>
              </span>
              {firstNote && <span className="line-clamp-1 text-xs text-muted-foreground">{firstNote}</span>}
            </button>
            <div className="absolute top-2 right-2">
              <RowMenu
                label={`Actions for ${e.source_name}`}
                items={[
                  { label: "Edit", onSelect: () => onEdit(e), hidden: !canManage },
                  { label: "Remove", onSelect: () => onRemove(e), destructive: true, hidden: !canManage },
                ]}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
