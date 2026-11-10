"use client";

import { Suspense } from "react";

import { IocManagementView } from "@/components/intelligence/ioc/ioc-management-view";

// `useSearchParams` (`?view=`) di client page wajib dibungkus Suspense (Next 16).
export default function IocManagementPage() {
  return (
    <Suspense fallback={null}>
      <IocManagementView />
    </Suspense>
  );
}
