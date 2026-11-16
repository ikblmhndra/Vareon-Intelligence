"use client";

import { cn } from "@/lib/utils";

interface ShowAllProps {
  total: number;
  shown: number;
  expanded: boolean;
  onToggle: () => void;
}

/** Pengembang daftar Exec (D16): "Show all (n)" / "Show fewer". Tombol asli, jadi Enter/Space bekerja bawaan.
 * Disembunyikan bila semua baris sudah tampil dan daftar tidak sedang dikembangkan. */
export function ShowAll({ total, shown, expanded, onToggle }: ShowAllProps) {
  if (total <= shown && !expanded) return null;
  return (
    <button
      type="button"
      aria-expanded={expanded}
      onClick={onToggle}
      className={cn(
        "rounded-md text-xs font-medium text-primary-text outline-none hover:underline",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
      )}
    >
      {expanded ? "Show fewer" : `Show all (${total})`}
    </button>
  );
}
