"use client";

import { CheckIcon, DownloadIcon, SaveIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EXEC_DAY_OPTIONS, EXEC_ROLE_PREVIEW_OPTIONS, type ExecFilters } from "@/lib/exec/filters";
import { useCan } from "@/lib/auth/permissions";

function selectItems(values: (string | number)[]): Record<string, string> {
  return Object.fromEntries(values.map((v) => [String(v), String(v)]));
}

interface ExecFilterBarProps {
  filters: ExecFilters;
  onChange: (next: ExecFilters) => void;
  isAdmin: boolean;
  viewRole: string | null;
  onSaveWatchlist: () => void;
  onClearWatchlist: () => void;
  watchlistSaved: boolean;
  onGenerateBrief: () => void;
  briefPending: boolean;
  onExportCsv: () => void;
  exportDisabled: boolean;
}

const ROLE_ALL = "__none__";

/** Port filter row + role switcher + watchlist buttons + brief/export
 * trigger (`exec.js` top strip). Semua kontrol apply LANGSUNG (gak ada
 * tombol Apply terpisah kayak `/cve`/`/newsroom`) -- port apa adanya,
 * `loadExecDashboard()` legacy juga langsung baca DOM tiap kali dipanggil
 * ulang lewat event `onchange` per kontrol. */
export function ExecFilterBar({
  filters,
  onChange,
  isAdmin,
  viewRole,
  onSaveWatchlist,
  onClearWatchlist,
  watchlistSaved,
  onGenerateBrief,
  briefPending,
  onExportCsv,
  exportDisabled,
}: ExecFilterBarProps) {
  function set<K extends keyof ExecFilters>(key: K, value: ExecFilters[K]) {
    onChange({ ...filters, [key]: value });
  }

  const can = useCan();

  return (
    <div className="mb-4 flex flex-wrap items-end gap-2 border-b border-border pb-3">
      <div className="flex flex-col gap-1">
        <Label className="text-sm font-medium text-muted-foreground">Period</Label>
        <Select
          items={selectItems(EXEC_DAY_OPTIONS)}
          value={String(filters.days)}
          onValueChange={(v) => v && set("days", Number(v))}
        >
          <SelectTrigger size="sm" className="w-28 font-mono text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {EXEC_DAY_OPTIONS.map((d) => (
              <SelectItem key={d} value={String(d)} className="font-mono text-xs">
                {d} days
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <label className="mb-1.5 flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
        <Checkbox checked={filters.incidentOnly} onCheckedChange={(c) => set("incidentOnly", c === true)} />
        Threat news only
      </label>
      <label className="mb-1.5 flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
        <Checkbox checked={filters.confirmedOnly} onCheckedChange={(c) => set("confirmedOnly", c === true)} />
        Confirmed only
      </label>

      {isAdmin && (
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Role preview</Label>
          <Select
            items={{ [ROLE_ALL]: "— none —", ...selectItems(EXEC_ROLE_PREVIEW_OPTIONS) }}
            value={filters.rolePreview || ROLE_ALL}
            onValueChange={(v) => set("rolePreview", v === ROLE_ALL ? "" : (v ?? ""))}
          >
            <SelectTrigger size="sm" className="w-32 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ROLE_ALL} className="font-mono text-xs">
                — none —
              </SelectItem>
              {EXEC_ROLE_PREVIEW_OPTIONS.map((r) => (
                <SelectItem key={r} value={r} className="font-mono text-xs">
                  {r}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {viewRole && (
        <Badge variant="outline" className="mb-1.5 font-mono text-xs">
          View: {viewRole.toUpperCase()}
        </Badge>
      )}

      <div className="ml-auto flex items-end gap-2">
        {watchlistSaved ? (
          <Button size="sm" variant="outline" className="text-success" onClick={onClearWatchlist}>
            <CheckIcon aria-hidden /> View saved
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={onSaveWatchlist}>
            <SaveIcon aria-hidden /> Save view
          </Button>
        )}
        <Button size="sm" variant="outline" disabled={exportDisabled} onClick={onExportCsv}>
          <DownloadIcon /> Export CSV
        </Button>
        {can("manage_intel") && (
          <Button size="sm" disabled={briefPending} onClick={onGenerateBrief}>
            {briefPending ? "Generating…" : "Generate Brief"}
          </Button>
        )}
      </div>
    </div>
  );
}
