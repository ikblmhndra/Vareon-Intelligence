import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "CVE Tracker" };

export default function CveLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader
        title="CVE Tracker"
        description="CVEs matched to your monitored tech, with ticketing, package vulnerabilities and the full CVE database."
      />
      {children}
    </>
  );
}
