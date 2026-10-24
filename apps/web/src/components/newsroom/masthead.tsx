"use client";

import { useEffect, useRef, useState } from "react";

import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { periodStart, useFilterOptions, type NewsroomFilters } from "@/lib/newsroom/filters";
import { cn } from "@/lib/utils";

const ALL = "__all__";

const PERIODS = [
  { label: "24 jam", days: 1 },
  { label: "7 hari", days: 7 },
  { label: "30 hari", days: 30 },
  { label: "Semua", days: 0 },
];

const CHIP =
  "h-8 rounded-full border px-3 text-xs font-medium focus-visible:ring-3 focus-visible:ring-focus focus-visible:outline-none";

const TODAY = new Intl.DateTimeFormat("id-ID", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});

/** Kepala halaman Newsroom + baris filter. Semua perubahan berlaku langsung
 * (tanpa Apply/Reset); pencarian di-debounce 300 ms supaya tidak menembak API
 * tiap ketukan. */
export function Masthead({
  filters,
  onChange,
  total,
}: {
  filters: NewsroomFilters;
  onChange: (f: NewsroomFilters) => void;
  total?: number;
}) {
  const options = useFilterOptions();
  const [search, setSearch] = useState(filters.search);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Handler debounce menutup `filters` lama; ref menjaga nilai terbaru yang dipakai.
  const latest = useRef({ filters, onChange });
  useEffect(() => {
    latest.current = { filters, onChange };
  });
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  function onSearch(value: string) {
    setSearch(value);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const { filters: f, onChange: change } = latest.current;
      change({ ...f, search: value.trim() });
    }, 300);
  }

  const activeDays = PERIODS.find((p) => p.days !== 0 && periodStart(p.days) === filters.dateStart)?.days
    ?? (filters.dateStart === "" ? 0 : -1);
  const countries = options.data?.countries ?? [];
  const items: Record<string, string> = { [ALL]: "Semua negara", ...Object.fromEntries(countries.map((c) => [c, c])) };

  return (
    <header className="mb-6 border-b border-border pb-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h1 className="text-3xl font-bold tracking-tight">Newsroom</h1>
        <p className="text-xs text-muted-foreground" suppressHydrationWarning>
          {TODAY.format(new Date())}
          {total !== undefined && <span> · {total.toLocaleString()} artikel</span>}
        </p>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Periode" className="flex flex-wrap gap-2">
          {PERIODS.map((p) => (
            <button
              key={p.label}
              type="button"
              aria-pressed={activeDays === p.days}
              onClick={() => onChange({ ...filters, dateStart: periodStart(p.days), dateEnd: "" })}
              className={cn(
                CHIP,
                activeDays === p.days
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border text-foreground hover:bg-muted",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          aria-pressed={filters.incidentOnly}
          onClick={() => onChange({ ...filters, incidentOnly: !filters.incidentOnly })}
          className={cn(
            CHIP,
            filters.incidentOnly
              ? "border-primary bg-primary text-primary-foreground"
              : "border-border text-foreground hover:bg-muted",
          )}
        >
          Insiden saja
        </button>
        <Select
          items={items}
          value={filters.country ?? ALL}
          onValueChange={(v) => onChange({ ...filters, country: !v || v === ALL ? null : v })}
        >
          <SelectTrigger aria-label="Negara" className="w-36 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL} className="text-xs">
              Semua negara
            </SelectItem>
            {countries.map((c) => (
              <SelectItem key={c} value={c} className="text-xs">
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          type="search"
          aria-label="Cari artikel"
          placeholder="Cari judul, aktor, CVE…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          className="min-w-48 flex-1 text-xs sm:max-w-xs"
        />
      </div>
    </header>
  );
}
