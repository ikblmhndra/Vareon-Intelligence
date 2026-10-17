"use client";

import { useMemo, useState } from "react";

import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

interface Option {
  value: string;
  label: string;
}

interface MultiSelectFieldProps {
  label: string;
  options: Option[];
  selected: string[];
  onChange: (next: string[]) => void;
}

/** Port `pirMsXxx()` multi-select (`exec.js:761-857`) -- dipakai buat 5
 * field criteria PIR (`tas`/`industries`/`countries`/`news_types`/
 * `ttps`). Base UI gak punya komponen multi-select/combobox siap pakai,
 * dibangun sendiri (Input+dropdown+tag chips), sama pola kayak
 * autocomplete Source Reliability Grup G1 tapi versi multi-pick. */
export function MultiSelectField({ label, options, selected, onChange }: MultiSelectFieldProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);

  const labelByValue = useMemo(() => new Map(options.map((o) => [o.value, o.label])), [options]);
  const matches = useMemo(() => {
    const q = query.toLowerCase();
    const unselected = options.filter((o) => !selected.includes(o.value));
    return q ? unselected.filter((o) => o.label.toLowerCase().includes(q)) : unselected;
  }, [options, selected, query]);

  function toggle(value: string) {
    if (selected.includes(value)) onChange(selected.filter((v) => v !== value));
    else onChange([...selected, value]);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!open || matches.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, matches.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && activeIdx >= 0) {
      e.preventDefault();
      toggle(matches[activeIdx].value);
      setQuery("");
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="relative flex flex-col gap-1">
      <Label className="text-sm font-medium text-muted-foreground">{label}</Label>
      <div className="flex min-h-8 flex-wrap items-center gap-1 rounded-lg border border-input bg-transparent px-2 py-1">
        {selected.map((v) => (
          <span key={v} className="flex items-center gap-1 rounded bg-primary/15 px-1.5 py-0.5 font-mono text-xs text-primary-text">
            {labelByValue.get(v) ?? v}
            <button type="button" className="hover:text-destructive" onClick={() => toggle(v)}>
              ×
            </button>
          </span>
        ))}
        <input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setActiveIdx(-1);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={handleKeyDown}
          placeholder={selected.length === 0 ? "Select…" : ""}
          className="min-w-[60px] flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
        />
      </div>
      {open && (
        <ul className="absolute top-full z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-md border border-border bg-popover shadow-md">
          {matches.length === 0 ? (
            <li className="px-3 py-2 text-xs text-muted-foreground">No options available</li>
          ) : (
            matches.map((o, i) => (
              <li
                key={o.value}
                className={cn("cursor-pointer px-3 py-1.5 text-xs", i === activeIdx ? "bg-accent text-accent-foreground" : "hover:bg-accent")}
                onMouseDown={() => {
                  toggle(o.value);
                  setQuery("");
                }}
              >
                {o.label}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
