import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Recap" };

export default function RecapLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader title="Recap" description="Daily and weekly intelligence recaps, with the full history." />
      {children}
    </>
  );
}
