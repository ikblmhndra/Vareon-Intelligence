"use client";

import { useRef, type KeyboardEvent } from "react";

import { cn } from "@/lib/utils";

export interface TabPillItem<T extends string> {
  value: T;
  label: string;
  /** `destructive` = tab untuk konten "di luar cakupan" (mis. Newsroom > Not Related Cyber). */
  tone?: "default" | "destructive";
}

/** Kelas satu pil. Dipakai juga `IntelligenceNav` (tautan antar-route, bukan tab). */
export function tabPillClass(active: boolean, tone: "default" | "destructive" = "default") {
  return cn(
    "shrink-0 whitespace-nowrap rounded-full border px-4 py-2 text-sm font-medium transition-colors duration-200",
    active
      ? tone === "destructive"
        ? "border-destructive/40 bg-destructive/10 text-destructive-text"
        : "border-primary/30 bg-primary/10 text-primary-text"
      : "border-border bg-surface text-muted-foreground hover:bg-muted hover:text-foreground",
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
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const current = items.findIndex((item) => item.value === value);
    let next: number;
    if (e.key === "ArrowRight") next = (current + 1) % items.length;
    else if (e.key === "ArrowLeft") next = (current - 1 + items.length) % items.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = items.length - 1;
    else return;
    e.preventDefault();
    onChange(items[next].value);
    refs.current[next]?.focus();
  }

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
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(item.value)}
            className={tabPillClass(active, item.tone)}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
