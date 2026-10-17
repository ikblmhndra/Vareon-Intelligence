import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Newsletter" };

export default function NewsletterLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader title="Newsletter" description="Compose the newsletter from suggested articles, then preview it." />
      {children}
    </>
  );
}
