"use client";

import type { components } from "@/lib/api/schema";

type EntityDetail = components["schemas"]["EntityDetail"];

/** PLACEHOLDER (Task 7): isi tab CVEs diganti di task berikutnya tanpa menyentuh `entity-view.tsx`. */
export function EntityCvesTab({ entity }: { entity: EntityDetail }) {
  return (
    <p className="text-sm text-muted-foreground" data-entity-id={entity.id}>
      CVEs tab is not available yet.
    </p>
  );
}
