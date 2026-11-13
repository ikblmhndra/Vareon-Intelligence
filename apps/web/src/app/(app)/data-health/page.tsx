"use client";

import { DataHealthView } from "@/components/data-health/data-health-view";
import { PageHeader } from "@/components/page-header";
import { usePageTitle } from "@/lib/use-page-title";

export default function DataHealthPage() {
  usePageTitle("Data health");
  return (
    <>
      <PageHeader
        title="Data health"
        description="Whether the pipeline is collecting, enriching and keeping its sources fresh, in one place."
      />
      <DataHealthView />
    </>
  );
}
