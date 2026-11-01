"use client";

import { Suspense, use } from "react";

import { EntityView } from "@/components/entities/entity-view";

// `params` adalah Promise di Next 16; di client page dibuka dengan `use()`.
// `useSearchParams` (tab) wajib dibungkus Suspense.
export default function EntityPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const numeric = Number(id);
  if (!Number.isInteger(numeric) || numeric <= 0) {
    return <p className="text-sm text-muted-foreground">Entity not found.</p>;
  }
  return (
    <Suspense fallback={null}>
      <EntityView id={numeric} />
    </Suspense>
  );
}
