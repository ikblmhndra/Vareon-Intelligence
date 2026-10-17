import type { Metadata } from "next";

import { IntelligenceNav } from "@/components/intelligence/intelligence-nav";
import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Intelligence" };

export default function IntelligenceLayout({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <PageHeader
        title="Intelligence"
        description="Threat actors, campaigns, IOCs and ATT&CK, plus PIR, RFI and early warning."
      />
      <IntelligenceNav />
      {children}
    </div>
  );
}
