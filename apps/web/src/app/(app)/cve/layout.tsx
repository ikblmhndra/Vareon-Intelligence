import type { Metadata } from "next";

export const metadata: Metadata = { title: "CVE Tracker" };

export default function CveLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <h1 className="sr-only">CVE Tracker</h1>
      {children}
    </>
  );
}
