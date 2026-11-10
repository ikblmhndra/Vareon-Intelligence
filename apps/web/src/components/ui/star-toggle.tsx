"use client";

import { StarIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface StarToggleProps {
  on: boolean;
  onToggle?: () => void;
  name: string;
  disabled?: boolean;
}

/** Bintang "watch" untuk entitas. Dengan `onToggle` = tombol (`aria-pressed`, target 24 px); tanpa itu = penanda
 * baca-saja yang tetap menyebut status ke pembaca layar. */
export function StarToggle({ on, onToggle, name, disabled }: StarToggleProps) {
  const icon = (
    <StarIcon aria-hidden="true" className={cn("size-4", on ? "fill-primary text-primary" : "text-muted-foreground")} />
  );
  if (!onToggle) {
    return (
      <span role="img" aria-label={on ? `Watching ${name}` : `Not watching ${name}`} className="inline-flex size-6 items-center justify-center">
        {icon}
      </span>
    );
  }
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={on ? `Stop watching ${name}` : `Watch ${name}`}
      disabled={disabled}
      onClick={onToggle}
      className="inline-flex size-6 items-center justify-center rounded-md outline-none transition-colors hover:bg-surface focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
    >
      {icon}
    </button>
  );
}
