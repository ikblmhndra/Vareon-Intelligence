"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

interface FilterSelectProps<T extends string> {
  prefix: string;
  value: T;
  onChange: (value: T) => void;
  options: readonly { value: T; label: string }[];
  "aria-label"?: string;
  className?: string;
}

/** Filter dropdown ringkas dengan trigger "{prefix}: {label}" (mis. "Severity: all"). `items` diteruskan ke
 * `Select` supaya label terpilih terselesaikan sebelum popup pernah dibuka. */
export function FilterSelect<T extends string>({
  prefix,
  value,
  onChange,
  options,
  "aria-label": ariaLabel,
  className,
}: FilterSelectProps<T>) {
  const items = Object.fromEntries(options.map((o) => [o.value, `${prefix}: ${o.label}`]));
  return (
    <Select items={items} value={value} onValueChange={(v) => v != null && onChange(v as T)}>
      <SelectTrigger aria-label={ariaLabel ?? prefix} size="sm" className={className}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
