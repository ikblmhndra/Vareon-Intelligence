import { Badge } from "@/components/ui/badge";
import { EntityChip } from "@/components/entities/entity-chip";
import { cveIdsIn } from "@/lib/entities/name-chips";
import { cn } from "@/lib/utils";

/**
 * Potongan kecil yang dipakai bersama `recap-view.tsx` dan `recap-quality.tsx`. Dipisah dari
 * `recap-view.tsx` supaya blok kualitas bisa memakainya tanpa import melingkar.
 */

export function EmptyNote() {
  return <p className="text-xs text-muted-foreground italic">(none)</p>;
}

export function ConfidenceBadge({ confidence }: { confidence?: string }) {
  const c = (confidence || "low").toLowerCase();
  const styles: Record<string, string> = {
    high: "border-success/50 bg-success/10 text-success-text",
    med: "border-warning/50 bg-warning/10 text-warning-text",
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

/**
 * Daftar nama recap. Dengan `entity`, nama aktor (`intrusion-set`) menjadi chip entity; untuk
 * `vulnerability` isinya bisa prosa ("CVE-2024-3400 (PAN-OS) ..."), jadi chip hanya untuk id CVE
 * yang ditemukan dan prosanya tetap Badge.
 */
export function Chips({ items, entity }: { items?: string[]; entity?: "intrusion-set" | "vulnerability" }) {
  if (!items || !items.length) return <EmptyNote />;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((v) => {
        if (entity === "intrusion-set") return <EntityChip key={v} type={entity} name={v} />;
        if (entity === "vulnerability") {
          const ids = cveIdsIn(v);
          if (ids.length === 1 && ids[0] === v.trim().toUpperCase()) return <EntityChip key={v} type={entity} name={ids[0]} />;
          if (ids.length > 0) {
            return (
              <span key={v} className="inline-flex flex-wrap items-center gap-1.5">
                {ids.map((id) => (
                  <EntityChip key={id} type={entity} name={id} />
                ))}
                <span className="text-sm text-muted-foreground">{v}</span>
              </span>
            );
          }
        }
        return (
          <Badge
            key={v}
            variant="outline"
            className="border-primary/40 bg-primary/10 font-mono text-sm text-primary-text"
          >
            {v}
          </Badge>
        );
      })}
    </div>
  );
}
