"use client";

import { ChevronDownIcon } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Bagian yang bisa dilipat. `printOpen`: tombol disembunyikan saat cetak dan isinya tetap tampil
 * walau terlipat, supaya hasil cetak/PDF tidak kehilangan bagian itu.
 */
export function Disclosure({
  title,
  defaultOpen = false,
  printOpen = false,
  children,
  className,
}: {
  title: ReactNode;
  defaultOpen?: boolean;
  printOpen?: boolean;
  children: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className={className}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex w-full items-center gap-2 rounded-md py-1.5 text-left text-sm font-semibold text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          printOpen && "print:hidden",
        )}
      >
        <ChevronDownIcon aria-hidden className={cn("size-4 shrink-0 transition-transform", !open && "-rotate-90")} />
        {title}
      </button>
      <div id={id} role="region" hidden={!open} className={cn(!open && printOpen && "print:block")}>
        {children}
      </div>
    </div>
  );
}
