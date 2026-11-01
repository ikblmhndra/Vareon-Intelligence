"use client";

import type { components } from "@/lib/api/schema";

type EntityDetail = components["schemas"]["EntityDetail"];

/** PLACEHOLDER (Task 7): isi tab Indicators diganti di task berikutnya tanpa menyentuh `entity-view.tsx`. */
export function EntityIndicatorsTab({ entity }: { entity: EntityDetail }) {
  return (
    <p className="text-sm text-muted-foreground" data-entity-id={entity.id}>
      Indicators tab is not available yet.
    </p>
  );
}
