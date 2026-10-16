import type { Metadata } from "next";

// Halaman ini sudah punya `<h1>` kasatmata sendiri, jadi layout cuma mengisi judul tab.
export const metadata: Metadata = { title: "Dashboard" };

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return children;
}
