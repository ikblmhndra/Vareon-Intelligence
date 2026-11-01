"use client";

import { Suspense } from "react";

import { EntitiesListView } from "@/components/entities/entities-list-view";

// `useSearchParams` di client page wajib dibungkus Suspense (Next 16).
export default function EntitiesPage() {
  return (
    <Suspense fallback={null}>
      <EntitiesListView />
    </Suspense>
  );
}
