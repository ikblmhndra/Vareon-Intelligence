import type { Metadata } from "next";

export const metadata: Metadata = { title: "Newsletter" };

export default function NewsletterLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <h1 className="sr-only">Newsletter</h1>
      {children}
    </>
  );
}
