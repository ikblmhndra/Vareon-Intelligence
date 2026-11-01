"use client";

import { Suspense } from "react";

import { EntityResolveView } from "@/components/entities/entity-resolve-view";

// `useSearchParams` di client page wajib dibungkus Suspense (Next 16).
export default function EntityResolvePage() {
  return (
    <Suspense fallback={null}>
      <EntityResolveView />
    </Suspense>
  );
}
