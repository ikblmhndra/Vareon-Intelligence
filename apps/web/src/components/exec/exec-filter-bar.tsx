"use client";

import { DownloadIcon, StarIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Chip } from "@/components/ui/chip";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EXEC_DAY_OPTIONS, EXEC_ROLE_PREVIEW_OPTIONS, type ExecFilters } from "@/lib/exec/filters";
import { cn } from "@/lib/utils";

const DAY_SEGMENTS = EXEC_DAY_OPTIONS.map((d) => ({ value: String(d), label: `${d}d` }));

// Sentinel "None": Base UI Select tidak menerima string kosong sebagai nilai item.
const ROLE_NONE = "__none__";
const ROLE_ITEMS: Record<string, string> = {
  [ROLE_NONE]: "Role preview: None",
  ...Object.fromEntries(EXEC_ROLE_PREVIEW_OPTIONS.map((r) => [r, `Role preview: ${r}`])),
};

interface ExecFilterBarProps {
  filters: ExecFilters;
  onChange: (next: ExecFilters) => void;
  isAdmin: boolean;
  viewRole: string | null;
  watchlistSaved: boolean;
  onToggleWatchlist: () => void;
  /** Hanya dikirim bila user punya `export_data`; tanpa itu tombol tidak dirender. */
  onExportCsv?: () => void;
  /** Data belum ada: tombol Export tampil tapi mati. */
  exportDisabled?: boolean;
  /** Hanya dikirim bila user punya `manage_intel`. */
  onGenerateBrief?: () => void;
  generating: boolean;
}

/** Toolbar Exec (kedua tampilan). Semua kontrol berlaku langsung (tanpa tombol Apply), seperti legacy. */
export function ExecFilterBar({
  filters,
  onChange,
  isAdmin,
  viewRole,
  watchlistSaved,
  onToggleWatchlist,
  onExportCsv,
  exportDisabled,
  onGenerateBrief,
  generating,
}: ExecFilterBarProps) {
  function set<K extends keyof ExecFilters>(key: K, value: ExecFilters[K]) {
    onChange({ ...filters, [key]: value });
  }
  const previewing = isAdmin && filters.rolePreview !== "";

  return (
    <div className="mb-6 flex flex-wrap items-center gap-x-4 gap-y-3">
      <SegmentedControl
        aria-label="Period"
        size="sm"
        options={DAY_SEGMENTS}
        value={String(filters.days)}
        onChange={(v) => set("days", Number(v))}
      />
      <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
        <Checkbox
          aria-label="Threat news only"
          checked={filters.incidentOnly}
          onCheckedChange={(c) => set("incidentOnly", c === true)}
        />
        Threat news only
      </label>
      <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
        <Checkbox
          aria-label="Confirmed only"
          checked={filters.confirmedOnly}
          onCheckedChange={(c) => set("confirmedOnly", c === true)}
        />
        Confirmed only
      </label>

      {isAdmin && (
        <Select
          items={ROLE_ITEMS}
          value={filters.rolePreview || ROLE_NONE}
          onValueChange={(v) => set("rolePreview", !v || v === ROLE_NONE ? "" : v)}
        >
          <SelectTrigger size="sm" aria-label="Role preview" className="w-48 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ROLE_NONE}>None</SelectItem>
            {EXEC_ROLE_PREVIEW_OPTIONS.map((r) => (
              <SelectItem key={r} value={r}>
                {r}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      {previewing && (
        <Chip kind="flag" value="previewing">
          Previewing {viewRole ?? filters.rolePreview}
        </Chip>
      )}

      <div className="ml-auto flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" aria-pressed={watchlistSaved} onClick={onToggleWatchlist}>
          <StarIcon aria-hidden className={cn(watchlistSaved && "fill-primary text-primary")} />
          {watchlistSaved ? "Watchlist saved" : "Save watchlist"}
        </Button>
        {onExportCsv && (
          <Button size="sm" variant="outline" disabled={exportDisabled} onClick={onExportCsv}>
            <DownloadIcon aria-hidden /> Export CSV
          </Button>
        )}
        {onGenerateBrief && (
          <Button size="sm" loading={generating} onClick={onGenerateBrief}>
            {generating ? "Generating…" : "✦ Generate brief"}
          </Button>
        )}
      </div>
    </div>
  );
}
