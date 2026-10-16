import type { Metadata } from "next";

// `page.tsx` login adalah Client Component (tidak bisa mengekspor `metadata`), jadi judul tab di sini.
export const metadata: Metadata = { title: "Sign in" };

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return children;
}
