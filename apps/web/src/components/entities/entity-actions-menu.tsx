"use client";

import type { components } from "@/lib/api/schema";

type EntityDetail = components["schemas"]["EntityDetail"];

/** PLACEHOLDER (Task 8): menu Actions (edit, alias, merge, split, suppress) diisi di task berikutnya. */
export function EntityActionsMenu({ entity }: { entity: EntityDetail }) {
  void entity;
  return null;
}
