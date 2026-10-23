import type { Metadata } from "next";

export const metadata: Metadata = { title: "Newsroom" };

/** Judul halaman ada di masthead (`components/newsroom/masthead.tsx`), bukan PageHeader. */
export default function NewsroomLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
