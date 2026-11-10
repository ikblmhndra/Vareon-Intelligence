"use client";

import { CalendarIcon, XIcon } from "lucide-react";
import { useRef } from "react";

import { fmtShortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

interface DateFieldProps {
  id: string;
  /** `YYYY-MM-DD` (tanggal lokal, tanpa zona) atau null. */
  value: string | null;
  onChange: (v: string | null) => void;
  "aria-label"?: string;
  /** Tampilkan tombol hapus; tanpa ini tanggal selalu terisi setelah dipilih. */
  optional?: boolean;
}

/** Tombol bertanggal ("1 Nov 2026") yang membuka pemilih tanggal native lewat `showPicker()` pada
 * `<input type="date">` tersembunyi (fallback: fokus ke input bila `showPicker` tak ada/ditolak). Nilai tetap
 * string `YYYY-MM-DD`; tampilan lewat `fmtShortDate` (memakai `parseLocalDate`, jadi tidak bergeser sehari
 * di zona sebelah barat UTC). */
export function DateField({ id, value, onChange, "aria-label": ariaLabel, optional }: DateFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  function open() {
    const el = inputRef.current;
    if (!el) return;
    try {
      el.showPicker();
    } catch {
      el.focus();
    }
  }

  return (
    <div className="relative inline-flex items-center gap-1">
      <button
        type="button"
        id={id}
        aria-label={ariaLabel}
        onClick={open}
        className={cn(
          "inline-flex h-10 max-sm:h-11 min-w-36 items-center gap-2 rounded-[10px] border border-input bg-background px-3 text-[15px] outline-none transition-colors hover:bg-surface",
          "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          !value && "text-muted-foreground",
        )}
      >
        <CalendarIcon aria-hidden className="size-4 shrink-0" />
        {value ? fmtShortDate(value, { withYear: true }) : "Select date"}
      </button>
      {optional && value && (
        <button
          type="button"
          aria-label="Clear date"
          onClick={() => onChange(null)}
          className="inline-flex size-6 items-center justify-center rounded-md outline-none hover:bg-surface focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          <XIcon aria-hidden className="size-4" />
        </button>
      )}
      <input
        ref={inputRef}
        type="date"
        tabIndex={-1}
        aria-hidden="true"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="sr-only"
      />
    </div>
  );
}
