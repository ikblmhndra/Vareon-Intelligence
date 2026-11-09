"use client";

import type { ReactNode } from "react";
import { Switch as SwitchPrimitive } from "@base-ui/react/switch";

import { cn } from "@/lib/utils";

interface SwitchProps {
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
  "aria-label": string;
  label?: ReactNode;
  disabled?: boolean;
  className?: string;
}

/** Saklar nyala/mati: track 36x20, tinta (`bg-foreground`) saat nyala, `bg-border` saat mati.
 * Base UI memberi `role="switch"` + `aria-checked` dan Spasi untuk toggle. `label` opsional di kanan. */
export function Switch({
  checked,
  onCheckedChange,
  "aria-label": ariaLabel,
  label,
  disabled,
  className,
}: SwitchProps) {
  const control = (
    <SwitchPrimitive.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={ariaLabel}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-border transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background data-[checked]:bg-foreground disabled:cursor-not-allowed disabled:opacity-50",
        label ? undefined : className,
      )}
    >
      <SwitchPrimitive.Thumb className="pointer-events-none block size-4 translate-x-0.5 rounded-full bg-background transition-transform data-[checked]:translate-x-[18px]" />
    </SwitchPrimitive.Root>
  );
  if (!label) return control;
  return (
    <span className={cn("inline-flex items-center gap-2 text-sm text-foreground", className)}>
      {control}
      {label}
    </span>
  );
}
