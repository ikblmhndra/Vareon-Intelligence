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
  open: controlledOpen,
  onOpenChange,
  id: wrapperId,
  headingLevel,
}: {
  title: ReactNode;
  defaultOpen?: boolean;
  printOpen?: boolean;
  children: ReactNode;
  className?: string;
  /** Terkendali bila diisi; `onOpenChange` dipanggil saat tombol ditekan. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Id pembungkus, supaya tautan header bisa membuka dan men-scroll ke bagian ini. */
  id?: string;
  /** Bila diisi, tombol dibungkus `<h2>`/`<h3>` (judul berisi tombol, bukan sebaliknya). Saat cetak, judul tetap tampil dan hanya panah yang disembunyikan. */
  headingLevel?: 2 | 3;
}) {
  const [innerOpen, setInnerOpen] = useState(defaultOpen);
  const open = controlledOpen ?? innerOpen;
  const toggle = () => {
    onOpenChange?.(!open);
    if (controlledOpen === undefined) setInnerOpen(!open);
  };
  const id = useId();
  const Heading = headingLevel === 3 ? "h3" : "h2";
  const trigger = (
      <button
        type="button"
        id={`${id}-trigger`}
        aria-expanded={open}
        aria-controls={id}
        onClick={toggle}
        className={cn(
          "flex w-full items-center gap-2 rounded-md py-1.5 text-left text-sm font-semibold text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          printOpen && !headingLevel && "print:hidden",
        )}
      >
        <ChevronDownIcon
          aria-hidden
          className={cn("size-4 shrink-0 transition-transform", !open && "-rotate-90", printOpen && headingLevel && "print:hidden")}
        />
        {title}
      </button>
  );
  return (
    <div id={wrapperId} className={className}>
      {headingLevel ? (
        <Heading className="m-0 text-base font-normal">{trigger}</Heading>
      ) : (
        trigger
      )}
      {/* Bukan atribut `hidden`: preflight Tailwind v4 memaksa [hidden] display:none !important, jadi print:block kalah. */}
      <div
        id={id}
        role="region"
        aria-labelledby={`${id}-trigger`}
        className={cn(!open && "hidden", !open && printOpen && "print:block")}
      >
        {children}
      </div>
    </div>
  );
}
