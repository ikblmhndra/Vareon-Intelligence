"use client";

import { NewsletterView } from "@/components/newsletter/newsletter-view";

// Header dan judul tab dirender `NewsletterView`: aksi header (Preview, Generate edition, History) memakai state komposer.
export default function NewsletterPage() {
  return (
    <div className="pb-10">
      <NewsletterView />
    </div>
  );
}
