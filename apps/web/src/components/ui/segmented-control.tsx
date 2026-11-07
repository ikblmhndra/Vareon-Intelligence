"use client";

import { cn } from "@/lib/utils";

import { useRovingKeys } from "./use-roving-keys";

interface SegmentedControlProps<T extends string> {
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  "aria-label": string;
  size?: "sm" | "default";
  className?: string;
}

/** Kontrol segmen (pilih satu): `radiogroup` dengan roving tabindex; panah memindahkan sekaligus memilih. */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  "aria-label": ariaLabel,
  size = "default",
  className,
}: SegmentedControlProps<T>) {
  const { onKeyDown, setRef } = useRovingKeys(options, value, onChange);

  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={cn("inline-flex gap-0.5 rounded-[10px] bg-surface p-0.5", className)}
    >
      {options.map((opt, i) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            ref={setRef(i)}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(opt.value)}
            className={cn(
              "whitespace-nowrap rounded-[8px] text-[13px] font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              size === "sm" ? "px-2.5 py-1" : "px-3.5 py-1.5",
              active
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
