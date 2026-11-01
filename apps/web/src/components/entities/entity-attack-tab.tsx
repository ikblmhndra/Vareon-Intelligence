"use client";

import type { components } from "@/lib/api/schema";

type EntityDetail = components["schemas"]["EntityDetail"];

/** PLACEHOLDER (Task 7): isi tab ATT&CK diganti di task berikutnya tanpa menyentuh `entity-view.tsx`. */
export function EntityAttackTab({ entity }: { entity: EntityDetail }) {
  return (
    <p className="text-sm text-muted-foreground" data-entity-id={entity.id}>
      ATT&CK tab is not available yet.
    </p>
  );
}
