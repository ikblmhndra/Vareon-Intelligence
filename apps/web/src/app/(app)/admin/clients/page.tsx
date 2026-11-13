"use client";

import { AdminFrame } from "@/components/admin/admin-frame";
import { ClientsSection } from "@/components/admin/clients-section";

export default function AdminClientsPage() {
  return (
    <AdminFrame page="clients">
      <ClientsSection />
    </AdminFrame>
  );
}
