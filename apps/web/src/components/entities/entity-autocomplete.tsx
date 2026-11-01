"use client";

import { useEffect, useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

import { api } from "@/lib/api/client";
import { entityTypeMeta } from "@/lib/entities/types";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

interface EntityAutocompleteProps {
  label: string;
  /** Tipe entity yang dicari (`type=` di `/api/entities`). */
  types: string[];
  identityClass?: "class" | "organization";
  /** Nilai yang disimpan: nama kanonik (default) atau `external_id` (TTP = id teknik, negara = kode ISO). */
  store?: "name" | "external_id";
  value: string[];
  onChange: (next: string[]) => void;
  /** Label baca untuk nilai tersimpan (mis. kode negara -> nama); jatuh ke nilai itu sendiri. */
  labelFor?: (stored: string) => string | undefined;
  /** Teks bebas yang diketik -> nilai yang disimpan (mis. nama negara -> kode ISO). */
  resolveTyped?: (typed: string) => string;
  /** Tampilkan id (font-code) di depan label, untuk TTP. */
  showId?: boolean;
  help?: string;
}

/** Normalisasi untuk membandingkan query dengan nama/alias (huruf kecil, tanpa spasi/tanda baca). */
function norm(s: string): string {
  return s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
}

/** Alias yang cocok dengan query bila yang cocok BUKAN nama kanonik (null = nama/external_id cocok). */
function matchedAlias(q: string, name: string, aliases: string[], externalId: string | null): string | null {
  const n = norm(q);
  if (!n || norm(name).includes(n) || (externalId && norm(externalId).includes(n))) return null;
  return aliases.find((a) => norm(a).includes(n)) ?? null;
}

/** Input token dengan saran dari `/api/entities` (cari nama + alias, debounce 250 ms).
 * Enter selalu menambah teks apa adanya (nama tanpa entity, atau role tanpa `view_ta` -> 403,
 * saran disembunyikan dan muncul teks bantuan). Token adalah teks biasa: nama yang disimpan di
 * kriteria PIR tidak membawa entity_id, jadi tidak ada tautan di dalamnya. */
export function EntityAutocomplete({
  label,
  types,
  identityClass,
  store = "name",
  value,
  onChange,
  labelFor,
  resolveTyped,
  showId,
  help,
}: EntityAutocompleteProps) {
  const inputId = useId();
  const listId = `${inputId}-list`;
  const labelId = `${inputId}-label`;
  const [text, setText] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState({ sig: "", idx: -1 });
  const [forbidden, setForbidden] = useState(false);
  // Nama yang pernah muncul di saran sesi ini (untuk label token berbasis id).
  const [seen, setSeen] = useState<Record<string, string>>({});
  const Icon = entityTypeMeta(types[0], identityClass).Icon;
  const colorClass = entityTypeMeta(types[0], identityClass).colorClass;

  useEffect(() => {
    const t = setTimeout(() => setDebounced(text.trim()), 250);
    return () => clearTimeout(t);
  }, [text]);

  const typeParam = types.join(",");
  const suggestions = useQuery({
    queryKey: ["entities", "autocomplete", typeParam, identityClass ?? "", debounced],
    enabled: debounced.length >= 1 && !forbidden,
    retry: false,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/entities", {
        params: { query: { type: typeParam, identity_class: identityClass, q: debounced, limit: 8 } },
      });
      if (response.status === 403) {
        setForbidden(true);
        return [];
      }
      if (!data) throw new Error(`HTTP ${response.status}`);
      setSeen((cur) => {
        const next = { ...cur };
        for (const e of data.items) next[store === "external_id" ? (e.external_id ?? e.name) : e.name] = e.name;
        return next;
      });
      return data.items;
    },
  });

  const items = (suggestions.data ?? [])
    .map((e) => ({
      key: e.id,
      stored: store === "external_id" ? (e.external_id ?? e.name) : e.name,
      name: e.name,
      externalId: e.external_id,
      alias: matchedAlias(debounced, e.name, e.aliases, e.external_id),
    }))
    .filter((e) => !value.includes(e.stored));

  // Daftar saran berubah -> sorotan lama tidak berlaku lagi (diturunkan dari signature daftar).
  const itemsSig = items.map((i) => i.key).join(",");
  const activeIdx = active.sig === itemsSig ? active.idx : -1;
  const setActiveIdx = (f: number | ((i: number) => number)) =>
    setActive({ sig: itemsSig, idx: typeof f === "function" ? f(activeIdx) : f });

  function add(v: string, typed = false) {
    const t = (typed && resolveTyped ? resolveTyped(v.trim()) : v).trim();
    if (t && !value.includes(t)) onChange([...value, t]);
    setText("");
    setDebounced("");
    setActiveIdx(-1);
  }

  const showList = open && !forbidden && debounced.length >= 1 && items.length > 0;

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" && items.length) {
      e.preventDefault();
      setOpen(true);
      setActiveIdx((i) => Math.min(i + 1, items.length - 1));
    } else if (e.key === "ArrowUp" && items.length) {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      // Enter pada saran yang disorot memilihnya; selain itu teks diketik apa adanya.
      if (open && activeIdx >= 0 && items[activeIdx]) add(items[activeIdx].stored);
      else add(text, true);
    } else if (e.key === "Escape") {
      // Daftar terbuka: Escape hanya menutup daftar, bukan dialog PIR di sekelilingnya.
      if (showList) {
        e.preventDefault();
        e.stopPropagation();
        setOpen(false);
      }
    } else if (e.key === "Backspace" && !text && value.length) {
      onChange(value.slice(0, -1));
    }
  }


  return (
    <div className="relative flex flex-col gap-1">
      <Label id={labelId} htmlFor={inputId} className="text-sm font-medium text-muted-foreground">
        {label}
      </Label>
      <div className="flex min-h-8 flex-wrap items-center gap-1 rounded-lg border border-input bg-transparent px-2 py-1 focus-within:ring-3 focus-within:ring-focus max-sm:min-h-11">
        {value.map((v) => (
          <span
            key={v}
            className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-1.5 py-0.5 text-xs text-foreground"
          >
            <Icon aria-hidden className={cn("size-3.5 shrink-0", colorClass)} />
            {showId && <span className="font-code">{v}</span>}
            <span>{showId ? (labelFor?.(v) ?? seen[v] ?? "") : (labelFor?.(v) ?? seen[v] ?? v)}</span>
            <button
              type="button"
              aria-label={`Remove ${v}`}
              onClick={() => onChange(value.filter((x) => x !== v))}
              className="inline-flex size-6 items-center justify-center rounded text-muted-foreground outline-none max-sm:size-8 hover:text-destructive focus-visible:ring-3 focus-visible:ring-focus"
            >
              <X aria-hidden className="size-3.5" />
            </button>
          </span>
        ))}
        <input
          id={inputId}
          role="combobox"
          aria-labelledby={labelId}
          aria-expanded={showList}
          aria-controls={showList ? listId : undefined}
          aria-activedescendant={showList && activeIdx >= 0 ? `${inputId}-opt-${activeIdx}` : undefined}
          aria-autocomplete="list"
          autoComplete="off"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
            setActiveIdx(-1);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            setOpen(false);
            // Teks yang masih diketik jadi token (aturan sama dengan Enter).
            if (text.trim()) add(text, true);
          }}
          onKeyDown={onKeyDown}
          placeholder={value.length === 0 ? "Type a name, Enter to add" : ""}
          className="min-w-[60px] flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
        />
      </div>
      {help && <p className="text-2xs text-muted-foreground">{help}</p>}
      {forbidden && <p className="text-2xs text-muted-foreground">Suggestions unavailable for your role</p>}
      {showList && (
        <ul
          id={listId}
          role="listbox"
          aria-label={`${label} suggestions`}
          className="absolute top-full z-10 mt-1 max-h-56 w-full overflow-y-auto rounded-md border border-border bg-popover shadow-md"
        >
          {items.map((it, i) => (
            <li
              key={it.key}
              id={`${inputId}-opt-${i}`}
              role="option"
              aria-label={it.externalId && it.externalId !== it.name ? `${it.name} ${it.externalId}` : it.name}
              aria-selected={i === activeIdx}
              // mousedown (bukan click) supaya terjadi sebelum blur menutup daftar.
              onMouseDown={(e) => {
                e.preventDefault();
                add(it.stored);
              }}
              className={cn(
                "cursor-pointer px-3 py-1.5 text-xs",
                i === activeIdx ? "bg-accent text-accent-foreground" : "hover:bg-accent",
              )}
            >
              <span className="flex items-baseline gap-2">
                <span className="truncate">{it.name}</span>
                {it.externalId && it.externalId !== it.name && (
                  <span className="shrink-0 font-code text-2xs text-muted-foreground">{it.externalId}</span>
                )}
              </span>
              {it.alias && <span className="block truncate text-2xs text-muted-foreground">{`matches “${it.alias}”`}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
