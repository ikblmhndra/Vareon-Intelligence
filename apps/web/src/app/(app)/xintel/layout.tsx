import type { Metadata } from "next";

export const metadata: Metadata = { title: "X Intel" };

export default function XIntelLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <h1 className="sr-only">X Intel</h1>
      {children}
    </>
  );
}
