"use client";

import { NewsletterView } from "@/components/newsletter/newsletter-view";
import { PageHeader } from "@/components/page-header";
import { usePageTitle } from "@/lib/use-page-title";

export default function NewsletterPage() {
  usePageTitle("Newsletter");
  return (
    <div className="pb-10">
      <PageHeader title="Newsletter" description="Compose the newsletter from suggested articles, then preview it." />
      <NewsletterView />
    </div>
  );
}
