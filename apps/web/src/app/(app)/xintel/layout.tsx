import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "X Intel" };

export default function XIntelLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader title="X Intel" description="Tweets from monitored X accounts, and the accounts being watched." />
      {children}
    </>
  );
}
