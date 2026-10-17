"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { defaultNewsroomFilters, useFilterOptions, type NewsroomFilters } from "@/lib/newsroom/filters";

const ALL = "__all__";

interface FilterBarProps {
  draft: NewsroomFilters;
  onDraftChange: (next: NewsroomFilters) => void;
  onApply: () => void;
  onReset: () => void;
}

/** Base UI `Select.Value` cuma bisa resolve label item yang UDAH
 * ke-render (popup content di-portal, gak mounted sebelum dibuka
 * sekali) -- tanpa `items` di `Select.Root`, trigger nampilin VALUE
 * mentah (`__all__`) bukan label ("All Countries") pas belum pernah
 * dibuka. KETEMU LIVE Grup D. Fix: kasih `items` eksplisit, itu pola
 * yang didesain Base UI persis buat kasus ini. */
function selectItems(allLabel: string, values: string[]): Record<string, string> {
  return { [ALL]: allLabel, ...Object.fromEntries(values.map((v) => [v, v])) };
}

/**
 * Port `.filter-bar` (`newsroom.html`) + `getFilters()`/`applyFilters()`/
 * `resetFilters()`. SEMUA kontrol (termasuk 3 select) butuh klik APPLY --
 * legacy gak punya `onchange` di select manapun, beda dari X Intel punya
 * checkbox yang langsung apply (Grup C). Scope: `/newsroom` doang, BUKAN
 * dibagi ke `/dashboard` (legacy nge-share satu filter bar buat keduanya)
 * -- itu butuh state lintas-route yang belum ada arsitekturnya, dicatat
 * sebagai gap di docs/PROGRESS.md, bukan diselesaikan sambil lalu di sini.
 */
export function FilterBar({ draft, onDraftChange, onApply, onReset }: FilterBarProps) {
  const options = useFilterOptions();

  function set<K extends keyof NewsroomFilters>(key: K, value: NewsroomFilters[K]) {
    onDraftChange({ ...draft, [key]: value });
  }

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 border-b border-border pb-3">
      <span className="text-sm font-semibold text-muted-foreground">Filter</span>
      <Input
        placeholder="Search titles…"
        value={draft.search}
        onChange={(e) => set("search", e.target.value)}
        className="w-44 font-mono text-xs"
      />
      <span className="text-xs text-muted-foreground">From</span>
      <Input
        type="date" aria-label="From date"
        value={draft.dateStart}
        onChange={(e) => set("dateStart", e.target.value)}
        className="w-auto font-mono text-xs"
      />
      <span className="text-xs text-muted-foreground">To</span>
      <Input
        type="date" aria-label="To date"
        value={draft.dateEnd}
        onChange={(e) => set("dateEnd", e.target.value)}
        className="w-auto font-mono text-xs"
      />
      <Select
        items={selectItems("All Countries", options.data?.countries ?? [])}
        value={draft.country || ALL}
        onValueChange={(v) => set("country", v === ALL ? "" : (v ?? ""))}
      >
        <SelectTrigger size="sm" className="w-36 font-mono text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL} className="font-mono text-xs">
            All Countries
          </SelectItem>
          {options.data?.countries.map((c) => (
            <SelectItem key={c} value={c} className="font-mono text-xs">
              {c}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        items={selectItems("All Industries", options.data?.industries ?? [])}
        value={draft.industry || ALL}
        onValueChange={(v) => set("industry", v === ALL ? "" : (v ?? ""))}
      >
        <SelectTrigger size="sm" className="w-40 font-mono text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL} className="font-mono text-xs">
            All Industries
          </SelectItem>
          {options.data?.industries.map((i) => (
            <SelectItem key={i} value={i} className="font-mono text-xs">
              {i}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        items={selectItems("All Threat Actors", options.data?.threat_actors ?? [])}
        value={draft.actor || ALL}
        onValueChange={(v) => set("actor", v === ALL ? "" : (v ?? ""))}
      >
        <SelectTrigger size="sm" className="w-44 font-mono text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL} className="font-mono text-xs">
            All Threat Actors
          </SelectItem>
          {options.data?.threat_actors.map((a) => (
            <SelectItem key={a} value={a} className="font-mono text-xs">
              {a}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        size="sm"
        variant="outline"
        onClick={() => {
          onDraftChange(defaultNewsroomFilters());
          onReset();
        }}
      >
        Reset
      </Button>
      <Button size="sm" onClick={onApply}>
        Apply
      </Button>
    </div>
  );
}
