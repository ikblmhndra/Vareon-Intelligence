import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Scrapers" };

export default function ScrapersLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader
        title="Scrapers"
        description="Health of every scraper, with controls to run, enable or schedule them."
      />
      {children}
    </>
  );
}
