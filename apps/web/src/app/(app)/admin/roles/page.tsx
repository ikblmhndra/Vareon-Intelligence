import type { Metadata } from "next";

import { RolesView } from "@/components/admin/roles-view";

export const metadata: Metadata = { title: "Roles · Admin" };

export default function AdminRolesPage() {
  return <RolesView />;
}
