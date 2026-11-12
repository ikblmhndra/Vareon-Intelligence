"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { DateField } from "@/components/ui/date-field";
import { SearchInput } from "@/components/ui/search-input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useDebounced } from "@/lib/cve/catalog";
import {
  DEFAULT_FILTERS,
  isDefault,
  type Period,
  type Signal,
  type XIntelFilters,
} from "@/lib/xintel/filters";
import { cn } from "@/lib/utils";

const PERIODS: { value: Period; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
  { value: "custom", label: "Custom" },
];

const SIGNAL_ITEMS: Record<Signal | "all", string> = {
  all: "Signal: all",
  ot: "Signal: OT / ICS",
  zero_day: "Signal: Zero-day",
  databreach: "Signal: Data breach",
  report: "Signal: Report",
};

const TOGGLES = [
  { key: "confirmed", label: "Confirmed incidents" },
  { key: "apac", label: "APAC" },
  { key: "cve", label: "CVEs" },
] as const;

interface XIntelToolbarProps {
  value: XIntelFilters;
  onChange: (f: XIntelFilters) => void;
  total: number | undefined;
  confirmed: number | undefined;
  onRefresh: () => void;
}

export function XIntelToolbar({ value, onChange, total, confirmed, onRefresh }: XIntelToolbarProps) {
  const [text, setText] = useState(value.search);
  const [seen, setSeen] = useState(value.search);
  // Pencarian diubah dari luar (klik akun di rail, Clear filters): kotak ikut, tanpa memicu debounce balik.
  if (value.search !== seen) {
    setSeen(value.search);
    setText(value.search);
  }
  const debounced = useDebounced(text, 400);
  useEffect(() => {
    // Hanya nilai yang diketik sendiri (debounced === text) yang diterapkan; nilai kadaluarsa diabaikan.
    if (debounced === text && debounced !== value.search) onChange({ ...value, search: debounced });
  }, [debounced, text, value, onChange]);

  const set = (patch: Partial<XIntelFilters>) => onChange({ ...value, ...patch });

  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
      <SearchInput
        className="w-full sm:w-80"
        aria-label="Search posts"
        placeholder="Search text, handle, CVE or victim"
        value={text}
        onChange={setText}
        onEnter={() => set({ search: text })}
      />
      <SegmentedControl
        aria-label="Period"
        options={PERIODS}
        value={value.period}
        onChange={(period) => set({ period })}
      />
      {value.period === "custom" && (
        <>
          <DateField id="xintel-from" aria-label="From" optional value={value.from} onChange={(from) => set({ from })} />
          <DateField id="xintel-to" aria-label="To" optional value={value.to} onChange={(to) => set({ to })} />
        </>
      )}
      <Select items={SIGNAL_ITEMS} value={value.signal} onValueChange={(v) => set({ signal: v as Signal | "all" })}>
        <SelectTrigger aria-label="Signal" className="w-48">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {Object.entries(SIGNAL_ITEMS).map(([v, label]) => (
            <SelectItem key={v} value={v}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {TOGGLES.map((t) => (
        <Button
          key={t.key}
          variant="outline"
          aria-pressed={value[t.key]}
          onClick={() => set({ [t.key]: !value[t.key] })}
          className={cn(value[t.key] && "bg-foreground text-background hover:bg-foreground/90")}
        >
          {t.label}
        </Button>
      ))}
      <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
        <span>
          <span className="font-code">{total ?? "–"}</span> posts · <span className="font-code">{confirmed ?? "–"}</span>{" "}
          confirmed incidents
        </span>
        <Button variant="ghost" size="sm" onClick={onRefresh}>
          Refresh
        </Button>
        {!isDefault(value) && (
          <Button variant="ghost" size="sm" onClick={() => onChange(DEFAULT_FILTERS)}>
            Clear filters
          </Button>
        )}
      </div>
    </div>
  );
}
