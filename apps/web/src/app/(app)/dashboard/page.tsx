import type { Metadata } from "next";
import { Suspense } from "react";

import { DashboardView } from "@/components/dashboard/dashboard-view";

// Judul tab statis di server: h1 halaman adalah tanggal, bukan data, jadi tidak lewat `usePageTitle`.
// Tidak ada layout bersarang bermetadata (akan mereset template judul root).
export const metadata: Metadata = { title: "Dashboard" };

// `useSearchParams` di DashboardView mewajibkan batas Suspense saat build.
export default function DashboardPage() {
  return (
    <Suspense>
      <DashboardView />
    </Suspense>
  );
}
