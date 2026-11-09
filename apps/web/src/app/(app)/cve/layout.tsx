import type { Metadata } from "next";

import { CvePageHeader } from "@/components/cve/cve-page-header";
import { CveViewProvider } from "@/lib/cve/view-state";

export const metadata: Metadata = { title: "CVE Tracker" };

export default function CveLayout({ children }: { children: React.ReactNode }) {
  return (
    <CveViewProvider>
      <CvePageHeader />
      {children}
    </CveViewProvider>
  );
}
