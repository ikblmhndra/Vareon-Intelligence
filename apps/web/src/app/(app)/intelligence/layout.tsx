import type { Metadata } from "next";

import { IntelligencePageHeader } from "@/components/intelligence/intelligence-page-header";

export const metadata: Metadata = { title: "Intelligence" };

export default function IntelligenceLayout({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <IntelligencePageHeader />
      {children}
    </div>
  );
}
