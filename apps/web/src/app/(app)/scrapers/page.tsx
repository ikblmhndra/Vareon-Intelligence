"use client";

import { PageHeader } from "@/components/page-header";
import { ScrapersView } from "@/components/scrapers/scrapers-view";
import { usePageTitle } from "@/lib/use-page-title";

export default function ScrapersPage() {
  usePageTitle("Scrapers");
  return (
    <>
      <PageHeader
        title="Scrapers"
        description="Health of every scraper, with controls to run, enable or schedule them."
      />
      <ScrapersView />
    </>
  );
}
