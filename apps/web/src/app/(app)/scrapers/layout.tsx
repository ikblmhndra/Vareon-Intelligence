import type { Metadata } from "next";

export const metadata: Metadata = { title: "Scrapers" };

export default function ScrapersLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <h1 className="sr-only">Scrapers</h1>
      {children}
    </>
  );
}
