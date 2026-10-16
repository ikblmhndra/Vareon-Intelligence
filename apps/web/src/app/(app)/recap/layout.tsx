import type { Metadata } from "next";

export const metadata: Metadata = { title: "Recap" };

export default function RecapLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <h1 className="sr-only">Recap</h1>
      {children}
    </>
  );
}
