import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Data health" };

export default function DataHealthLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader
        title="Data health"
        description="Whether the pipeline is collecting, enriching and keeping its sources fresh, in one place."
      />
      {children}
    </>
  );
}
