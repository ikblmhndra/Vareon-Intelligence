"use client";

import { cn } from "@/lib/utils";

import { useRovingKeys } from "./use-roving-keys";

interface UnderlineTabsProps<T extends string> {
  items: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  /** Nama daftar tab untuk pembaca layar. */
  "aria-label": string;
  className?: string;
}

/** Tab bergaris bawah (mockup FigCraft): aktif = tinta + garis merah 2 px. Model ARIA tabs sama
 * dengan `TabPills` (roving tabindex, panah/Home/End, seleksi mengikuti fokus). Panel dirender pemanggil. */
export function UnderlineTabs<T extends string>({
  items,
  value,
  onChange,
  "aria-label": ariaLabel,
  className,
}: UnderlineTabsProps<T>) {
  const { onKeyDown, setRef } = useRovingKeys(items, value, onChange);

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={cn("flex gap-6 overflow-x-auto border-b border-border", className)}
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
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(item.value)}
            className={cn(
              "-mb-px shrink-0 whitespace-nowrap border-b-2 px-0.5 pb-2.5 text-[15px] font-semibold transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              active
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
