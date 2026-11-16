"use client";

import { SearchIcon } from "lucide-react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  "aria-label": string;
  onEnter?: () => void;
  className?: string;
}

/** Kolom cari dengan ikon kaca pembesar di kiri; `onEnter` dipanggil saat menekan Enter. */
export function SearchInput({
  value,
  onChange,
  placeholder,
  "aria-label": ariaLabel,
  onEnter,
  className,
}: SearchInputProps) {
  return (
    <div className={cn("relative", className)}>
      <SearchIcon
        aria-hidden="true"
        className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
      />
      <Input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onEnter?.();
        }}
        placeholder={placeholder}
        aria-label={ariaLabel}
        className="pl-9"
      />
    </div>
  );
}
