"use client";

import { Suspense, use } from "react";
import Link from "next/link";

import { EntityView } from "@/components/entities/entity-view";

// `params` adalah Promise di Next 16; di client page dibuka dengan `use()`.
// `useSearchParams` (tab) wajib dibungkus Suspense.
export default function EntityPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const numeric = Number(id);
  if (!Number.isInteger(numeric) || numeric <= 0) {
    return (
      <section className="surface-raised space-y-3 rounded-xl p-5">
        <h2 className="text-base font-semibold">Entity not found</h2>
        <Link href="/intelligence/entities" className="text-sm text-primary-text underline">
          Back to entities
        </Link>
      </section>
    );
  }
  return (
    <Suspense fallback={null}>
      <EntityView id={numeric} />
    </Suspense>
  );
}
