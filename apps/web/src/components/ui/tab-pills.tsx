"use client";

import { cn } from "@/lib/utils";

import { useRovingKeys } from "./use-roving-keys";

export interface TabPillItem<T extends string> {
  value: T;
  label: string;
  /** Lencana jumlah di samping label; kosong/undefined = tidak ditampilkan (mis. masih memuat). */
  count?: number;
  /** `destructive` = tab untuk konten "di luar cakupan" (mis. Newsroom > Not Related Cyber). */
  tone?: "default" | "destructive";
}

/** Kelas satu pil. Dipakai juga `IntelligenceNav` (tautan antar-route, bukan tab). */
export function tabPillClass(active: boolean, tone: "default" | "destructive" = "default") {
  return cn(
    "h-[31px] shrink-0 whitespace-nowrap rounded-full border px-3 py-[7px] text-xs font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
    active
      ? tone === "destructive"
        ? "border-destructive/40 bg-destructive/10 text-destructive-text"
        : "border-foreground bg-foreground text-background"
      : "border-border bg-background text-foreground hover:bg-surface",
  );
}

interface TabPillsProps<T extends string> {
  items: readonly TabPillItem<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Nama daftar tab untuk pembaca layar. */
  "aria-label": string;
  className?: string;
}

/** Pengganti 7 salinan markup tab pil. Pola ARIA tabs: `role=tablist/tab`, `aria-selected`,
 * roving tabindex, dan panah kiri/kanan + Home/End memindahkan sekaligus memilih tab (seleksi
 * mengikuti fokus, sama dengan perilaku klik). Panel isinya dirender pemanggil. */
export function TabPills<T extends string>({
  items,
  value,
  onChange,
  "aria-label": ariaLabel,
  className,
}: TabPillsProps<T>) {
  const { onKeyDown, setRef, tabIndexFor } = useRovingKeys(items, value, onChange);

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={cn("flex gap-1.5 overflow-x-auto", className)}
    >
      {items.map((item, i) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            ref={setRef(i)}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={tabIndexFor(i)}
            onClick={() => onChange(item.value)}
            className={tabPillClass(active, item.tone)}
          >
            {item.label}
            {item.count != null && (
              <span className="ml-1.5 rounded-full bg-panel px-1.5 py-0.5 font-code text-2xs text-muted-foreground">
                {item.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
