import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Admin" };

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader
        title="Admin"
        description="Users, roles, password policy, audit log, clients and third-party keys."
      />
      {children}
    </>
  );
}
