"use client";

import { Chip } from "@/components/ui/chip";
import { MeterBar } from "@/components/ui/meter-bar";
import { RowMenu } from "@/components/ui/row-menu";
import { SelectableList } from "@/components/ui/selectable-list";
import { fmtAgo } from "@/lib/format";
import { displayId, pirPriority } from "@/lib/intelligence/format";
import { PIR_CRITERIA_ROWS, PIR_PRIORITY_CHIP, type PIROut } from "@/lib/intelligence/pir";
import { cn } from "@/lib/utils";

interface PirListProps {
  pirs: PIROut[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  /** Izin dibaca halaman (`useCan`); item menu tanpa izin disembunyikan. */
  canManage: boolean;
  canExport: boolean;
  onEdit: (p: PIROut) => void;
  onExportJson: (p: PIROut) => void;
  onExportDocx: (p: PIROut) => void;
  onDelete: (p: PIROut) => void;
}

/** Lencana prioritas (P1/P2/P3 -> Critical/High/Medium, D15); nilai tersimpan lain tampil apa adanya. */
export function PirPriorityChip({ priority }: { priority: string }) {
  const p = pirPriority(priority);
  return (
    <Chip kind="flag" value={p.label} className={PIR_PRIORITY_CHIP[p.tone]}>
      {p.label}
    </Chip>
  );
}

/** Baris kriteria berlabel (hanya yang terisi). Teks biasa, bukan EntityChip: kartu adalah tombol option
 * yang tak boleh memuat tautan, dan kriteria PIR tidak membawa entity_id. */
export function PirCriteriaRows({ criteria, className }: { criteria: PIROut["criteria"]; className?: string }) {
  const rows = PIR_CRITERIA_ROWS.filter((r) => criteria[r.key].length > 0);
  if (rows.length === 0) return null;
  return (
    <div className={cn("flex flex-wrap gap-x-4 gap-y-1 text-xs text-foreground", className)}>
      {rows.map((r) => (
        <span key={r.key} className="min-w-0">
          <span className="mr-1.5 text-2xs font-semibold tracking-wide text-muted-foreground">{r.label}</span>
          <span className={cn(r.code && "font-code")}>{criteria[r.key].join(", ")}</span>
        </span>
      ))}
    </div>
  );
}

/** Daftar kartu PIR (spec 2b 6.4): kartu = option yang dapat dipilih (master-detail); aksi sekunder ada di
 * menu "⋯" di luar tombol kartu. Bar cakupan relatif terhadap PIR terbesar di tampilan ini. */
export function PirList({
  pirs,
  selectedId,
  onSelect,
  canManage,
  canExport,
  onEdit,
  onExportJson,
  onExportDocx,
  onDelete,
}: PirListProps) {
  const maxCov = Math.max(...pirs.map((p) => p.coverage_count), 1);
  const items = pirs.map((p) => ({ value: String(p.id), pir: p }));

  return (
    <SelectableList
      variant="card"
      aria-label="Priority intelligence requirements"
      items={items}
      value={selectedId != null ? String(selectedId) : null}
      onChange={(v) => onSelect(Number(v))}
      renderAction={({ pir: p }) => (
        <RowMenu
          label={`Actions for ${displayId("PIR", p.id)}`}
          items={[
            { label: "Edit", onSelect: () => onEdit(p), hidden: !canManage },
            { label: "Export JSON", onSelect: () => onExportJson(p), hidden: !canExport },
            { label: "Export DOCX", onSelect: () => onExportDocx(p), hidden: !canExport },
            { label: "Delete", onSelect: () => onDelete(p), destructive: true, hidden: !canManage },
          ]}
        />
      )}
      renderItem={({ pir: p }) => (
        <div className="flex flex-col gap-2">
          {/* pr-8: ruang untuk tombol "⋯" yang menumpang di pojok kanan atas. */}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 pr-8">
            <span className="font-code text-xs font-semibold text-foreground">{displayId("PIR", p.id)}</span>
            <PirPriorityChip priority={p.priority} />
            {p.is_gap && (
              <Chip kind="status" value="action">
                COVERAGE GAP
              </Chip>
            )}
            <span className="ml-auto text-2xs text-muted-foreground">
              {p.owner ? `Owner: ${p.owner} · ` : ""}last match{" "}
              {p.last_match ? fmtAgo(p.last_match) : "never"}
            </span>
          </div>
          <p className="font-heading text-base font-semibold text-foreground">{p.title}</p>
          <PirCriteriaRows criteria={p.criteria} />
          <MeterBar
            value={p.coverage_count}
            max={maxCov}
            tone={p.is_gap ? "destructive" : "neutral"}
            aria-label={`Coverage of ${displayId("PIR", p.id)}`}
            label={
              <span className={cn(p.is_gap && "font-semibold text-destructive-text")}>
                {p.coverage_count.toLocaleString()} articles matched · {p.recent_coverage.toLocaleString()} in 14
                days
              </span>
            }
          />
        </div>
      )}
    />
  );
}
