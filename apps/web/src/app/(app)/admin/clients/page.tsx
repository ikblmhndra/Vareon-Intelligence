import type { Metadata } from "next";

import { ClientsView } from "@/components/admin/clients-view";

export const metadata: Metadata = { title: "Clients · Admin" };

export default function AdminClientsPage() {
  return <ClientsView />;
}
