import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Exec" };

export default function ExecLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader
        title="Exec"
        description="Incident trends, sector risk, threat actors and CVE exposure at a glance."
      />
      {children}
    </>
  );
}
