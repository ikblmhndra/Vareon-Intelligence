import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Newsroom" };

export default function NewsroomLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader
        title="Newsroom"
        description="Enriched security news, with ransomware, local, watchlist and tech-stack views."
      />
      {children}
    </>
  );
}
