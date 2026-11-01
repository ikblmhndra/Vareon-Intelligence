"use client";

import type { components } from "@/lib/api/schema";

type EntityDetail = components["schemas"]["EntityDetail"];

/** PLACEHOLDER (Task 7): isi tab Relationships diganti di task berikutnya tanpa menyentuh `entity-view.tsx`. */
export function EntityRelationshipsTab({ entity }: { entity: EntityDetail }) {
  return (
    <p className="text-sm text-muted-foreground" data-entity-id={entity.id}>
      Relationships tab is not available yet.
    </p>
  );
}
