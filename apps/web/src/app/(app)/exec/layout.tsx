import type { Metadata } from "next";

export const metadata: Metadata = { title: "Exec" };

export default function ExecLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <h1 className="sr-only">Exec</h1>
      {children}
    </>
  );
}
