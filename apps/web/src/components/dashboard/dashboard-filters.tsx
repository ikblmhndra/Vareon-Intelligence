"use client";

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export interface DashboardFilters {
  /** `null` = all-time (gak ada periode sebelumnya buat dibandingkan). */
  days: number | null;
  incidentOnly: boolean;
}

export const DEFAULT_DASHBOARD_FILTERS: DashboardFilters = { days: 30, incidentOnly: true };

const PERIODS: { value: string; label: string }[] = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "all", label: "All time" },
];
const PERIOD_ITEMS = Object.fromEntries(PERIODS.map((p) => [p.value, p.label]));

/** Kontrol periode + "Incidents only" di header Dashboard -- pola sama dengan
 * `ExecFilterBar` (apply langsung, tanpa tombol Apply). `updatedAt` = `generated_at`
 * dari API: cache server 15 menit, jadi angka bisa lebih tua dari "sekarang". */
export function DashboardFilterBar({
  filters,
  onChange,
  updatedAt,
}: {
  filters: DashboardFilters;
  onChange: (next: DashboardFilters) => void;
  updatedAt?: string;
}) {
  const updated = updatedAt ? new Date(updatedAt) : null;
  return (
    <div className="flex flex-wrap items-end gap-3">
      <div className="flex flex-col gap-1">
        <Label className="text-sm font-medium text-muted-foreground">Period</Label>
        <Select
          items={PERIOD_ITEMS}
          value={filters.days === null ? "all" : String(filters.days)}
          onValueChange={(v) => v && onChange({ ...filters, days: v === "all" ? null : Number(v) })}
        >
          <SelectTrigger size="sm" className="w-36 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PERIODS.map((p) => (
              <SelectItem key={p.value} value={p.value} className="text-xs">
                {p.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <label className="mb-1.5 flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
        <Checkbox
          checked={filters.incidentOnly}
          onCheckedChange={(c) => onChange({ ...filters, incidentOnly: c === true })}
        />
        Incidents only
      </label>
      {updated && !Number.isNaN(updated.getTime()) && (
        <span className="mb-1.5 text-xs text-muted-foreground">
          Updated {updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </span>
      )}
    </div>
  );
}
