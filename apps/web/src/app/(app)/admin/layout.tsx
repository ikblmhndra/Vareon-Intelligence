import type { Metadata } from "next";

export const metadata: Metadata = { title: "Admin" };

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <h1 className="sr-only">Admin</h1>
      {children}
    </>
  );
}
