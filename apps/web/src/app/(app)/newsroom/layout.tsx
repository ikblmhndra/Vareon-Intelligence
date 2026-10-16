import type { Metadata } from "next";

export const metadata: Metadata = { title: "Newsroom" };

export default function NewsroomLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <h1 className="sr-only">Newsroom</h1>
      {children}
    </>
  );
}
