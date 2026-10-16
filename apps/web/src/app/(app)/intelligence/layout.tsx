import type { Metadata } from "next";

import { IntelligenceNav } from "@/components/intelligence/intelligence-nav";

export const metadata: Metadata = { title: "Intelligence" };

export default function IntelligenceLayout({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <h1 className="sr-only">Intelligence</h1>
      <IntelligenceNav />
      {children}
    </div>
  );
}
