import type { Metadata } from "next";

// Judul tab browser per segmen (D1); template root menambahkan nama platform.
export const metadata: Metadata = { title: "Campaign clusters" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
