"use client";

import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { defaultNewsroomFilters, useFilterOptions, type NewsroomFilters } from "@/lib/newsroom/filters";
import { cn } from "@/lib/utils";

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

/** Label di atas kontrol dan terhubung lewat `htmlFor`: placeholder bukan label, dan "From"/"To"
 * yang dulu berupa `<span>` lepas tidak terhubung ke inputnya. */
function Field({
  label,
  htmlFor,
  className,
  children,
}: {
  label: string;
  htmlFor: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <Label htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
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
    <div className="mb-4 grid grid-cols-2 items-end gap-3 border-b border-border pb-4 sm:flex sm:flex-wrap">
      <Field label="Search" htmlFor="nr-search" className="col-span-2 sm:col-span-1 sm:min-w-40 sm:flex-1 sm:basis-44">
        <Input
          id="nr-search"
          placeholder="Title keywords"
          value={draft.search}
          onChange={(e) => set("search", e.target.value)}
          className="text-xs"
        />
      </Field>
      <Field label="From" htmlFor="nr-from">
        <Input
          id="nr-from"
          type="date"
          value={draft.dateStart}
          onChange={(e) => set("dateStart", e.target.value)}
          className="w-full text-xs sm:w-36"
        />
      </Field>
      <Field label="To" htmlFor="nr-to">
        <Input
          id="nr-to"
          type="date"
          value={draft.dateEnd}
          onChange={(e) => set("dateEnd", e.target.value)}
          className="w-full text-xs sm:w-36"
        />
      </Field>
      <Field label="Country" htmlFor="nr-country">
        <Select
          items={selectItems("All Countries", options.data?.countries ?? [])}
          value={draft.country || ALL}
          onValueChange={(v) => set("country", v === ALL ? "" : (v ?? ""))}
        >
          <SelectTrigger id="nr-country" className="w-full text-xs sm:w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL} className="text-xs">
              All Countries
            </SelectItem>
            {options.data?.countries.map((c) => (
              <SelectItem key={c} value={c} className="text-xs">
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label="Industry" htmlFor="nr-industry">
        <Select
          items={selectItems("All Industries", options.data?.industries ?? [])}
          value={draft.industry || ALL}
          onValueChange={(v) => set("industry", v === ALL ? "" : (v ?? ""))}
        >
          <SelectTrigger id="nr-industry" className="w-full text-xs sm:w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL} className="text-xs">
              All Industries
            </SelectItem>
            {options.data?.industries.map((i) => (
              <SelectItem key={i} value={i} className="text-xs">
                {i}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label="Threat actor" htmlFor="nr-actor">
        <Select
          items={selectItems("All Threat Actors", options.data?.threat_actors ?? [])}
          value={draft.actor || ALL}
          onValueChange={(v) => set("actor", v === ALL ? "" : (v ?? ""))}
        >
          <SelectTrigger id="nr-actor" className="w-full text-xs sm:w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL} className="text-xs">
              All Threat Actors
            </SelectItem>
            {options.data?.threat_actors.map((a) => (
              <SelectItem key={a} value={a} className="text-xs">
                {a}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <div className="col-span-2 flex justify-end gap-2 sm:col-span-1 sm:ml-auto">
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
    </div>
  );
}
