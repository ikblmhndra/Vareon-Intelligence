import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * Potongan kecil yang dipakai bersama `recap-view.tsx` dan `recap-quality.tsx`. Dipisah dari
 * `recap-view.tsx` supaya blok kualitas bisa memakainya tanpa import melingkar (view memuat
 * kualitas, kualitas memakai `Section`).
 */

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mt-5 first:mt-0">
      <div className="mb-2 border-b border-border pb-1 text-sm font-semibold text-muted-foreground">
        {title}
      </div>
      {children}
    </div>
  );
}

export function EmptyNote() {
  return <p className="text-xs text-muted-foreground italic">(none)</p>;
}

export function ConfidenceBadge({ confidence }: { confidence?: string }) {
  const c = (confidence || "low").toLowerCase();
  const styles: Record<string, string> = {
    high: "border-success/50 bg-success/10 text-success",
    med: "border-warning/50 bg-warning/10 text-warning",
    low: "border-muted-foreground/50 bg-muted text-muted-foreground",
  };
  return (
    <Badge
      variant="outline"
      className={cn("font-mono text-xs uppercase", styles[c] ?? styles.low)}
    >
      {c}
    </Badge>
  );
}

export function Chips({ items }: { items?: string[] }) {
  if (!items || !items.length) return <EmptyNote />;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((v) => (
        <Badge
          key={v}
          variant="outline"
          className="border-primary/40 bg-primary/10 font-mono text-sm text-primary"
        >
          {v}
        </Badge>
      ))}
    </div>
  );
}
