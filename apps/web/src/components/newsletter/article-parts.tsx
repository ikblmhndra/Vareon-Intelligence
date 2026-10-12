"use client";

import type { ReactElement, ReactNode } from "react";

import { SectionIcon } from "@/components/newsletter/section-icon";
import { Badge } from "@/components/ui/badge";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import type { components } from "@/lib/api/schema";
import { SLOTS, type ComposerState, type SlotKey } from "@/lib/newsletter/composer";

type Reason = components["schemas"]["NewsletterSuggestionReason"];

/** Sinyal yang berarti "ini perlu dibaca" diberi warna; sisanya (cakupan, sumber, dst.) netral. */
const STRONG_REASONS = new Set(["kev", "poc", "confirmed_incident", "monitored_tech", "client_country"]);

/** Kenapa artikel disarankan (`reasons` dari ranking, teks Inggris singkat dari server). */
export function ReasonChips({ reasons }: { reasons: Reason[] | undefined }) {
  if (!reasons?.length) return null;
  return (
    <div className="flex flex-wrap gap-1" aria-label="Why this article was suggested">
      {reasons.map((r) => (
        <Badge
          key={r.code + r.text}
          variant={STRONG_REASONS.has(r.code) ? "destructive" : "outline"}
          className="h-auto max-w-full whitespace-normal py-0.5 text-left text-xs"
          title={r.code}
        >
          {r.text}
        </Badge>
      ))}
    </div>
  );
}

interface DestinationMenuProps {
  /** Dipakai menghitung slot yang penuh. */
  state: ComposerState;
  /** Slot tempat artikel berada sekarang (tidak ditawarkan lagi); kosong untuk artikel dari kolam. */
  current?: SlotKey | null;
  onPick: (slot: SlotKey) => void;
  /** Tombol pemicu (`render` Base UI, bukan `asChild`); isinya lewat `children`. */
  trigger: ReactElement;
  triggerLabel: string;
  children: ReactNode;
}

/**
 * Pilih tujuan artikel: Highlights, atau kartu penuh / "Also Noted" tiap section. Slot yang penuh
 * tampil nonaktif dengan keterangan, jadi batas terlihat sebelum analis mencoba, bukan hanya
 * sebagai pesan galat sesudahnya.
 */
export function DestinationMenu({ state, current, onPick, trigger, triggerLabel, children }: DestinationMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={trigger} aria-label={triggerLabel} title={triggerLabel}>
        {children}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {SLOTS.filter((s) => s.key !== current).map((s) => {
          const full = state.slots[s.key].length >= s.cap;
          return (
            <DropdownMenuItem key={s.key} disabled={full} onClick={() => onPick(s.key)}>
              <SectionIcon section={s.section ?? "highlights"} />
              {full ? `${s.label} (limit ${s.cap} reached)` : s.label}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
