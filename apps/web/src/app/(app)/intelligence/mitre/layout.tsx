import type { Metadata } from "next";

// Judul tab browser per segmen (D1); template root menambahkan nama platform.
export const metadata: Metadata = { title: "MITRE ATT&CK heatmap" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
