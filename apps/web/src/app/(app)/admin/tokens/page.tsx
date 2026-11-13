"use client";

import { Suspense } from "react";

import { TokensView } from "@/components/admin/tokens-view";

// `useSearchParams` (?new=1) di client component wajib dibungkus Suspense (Next 16).
export default function AdminTokensPage() {
  return (
    <Suspense>
      <TokensView />
    </Suspense>
  );
}
