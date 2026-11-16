"use client";

import type { ReactNode } from "react";
import { Radio } from "@base-ui/react/radio";
import { RadioGroup } from "@base-ui/react/radio-group";

import { cn } from "@/lib/utils";

interface RadioListProps<T extends string> {
  name: string;
  value: T | null;
  onChange: (value: T) => void;
  options: readonly {
    value: T;
    title: ReactNode;
    sub?: ReactNode;
    aside?: ReactNode;
    disabled?: boolean;
  }[];
  /** Nama grup untuk pembaca layar. */
  "aria-label": string;
}

/** Daftar radio berbaris (mockup FigCraft): tiap baris = judul + sub + sisi kanan opsional; terpilih =
 * border `foreground` + bulatan terisi. Base UI memberi `role=radiogroup/radio` dan navigasi panah. */
export function RadioList<T extends string>({
  name,
  value,
  onChange,
  options,
  "aria-label": ariaLabel,
}: RadioListProps<T>) {
  return (
    <RadioGroup
      name={name}
      value={value}
      onValueChange={(v) => onChange(v as T)}
      aria-label={ariaLabel}
      className="flex flex-col gap-2"
    >
      {options.map((o) => (
        <Radio.Root
          key={o.value}
          value={o.value}
          disabled={o.disabled}
          className={cn(
            "flex w-full items-center gap-3 rounded-lg border border-border bg-background px-3.5 py-3 text-left transition-colors outline-none hover:bg-surface focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background data-[checked]:border-foreground data-[disabled]:cursor-not-allowed data-[disabled]:bg-panel data-[disabled]:text-muted-foreground",
          )}
        >
          <span
            aria-hidden
            className="flex size-4 shrink-0 items-center justify-center rounded-full border border-border bg-background"
          >
            <Radio.Indicator className="size-2 rounded-full bg-foreground" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold">{o.title}</span>
            {o.sub && <span className="block text-xs text-muted-foreground">{o.sub}</span>}
          </span>
          {o.aside && <span className="shrink-0 text-xs text-muted-foreground">{o.aside}</span>}
        </Radio.Root>
      ))}
    </RadioGroup>
  );
}
