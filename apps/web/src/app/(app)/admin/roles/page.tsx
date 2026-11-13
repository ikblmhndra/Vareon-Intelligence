"use client";

import { AdminFrame } from "@/components/admin/admin-frame";
import { RolesSection } from "@/components/admin/roles-section";

export default function AdminRolesPage() {
  return (
    <AdminFrame page="roles">
      <RolesSection />
    </AdminFrame>
  );
}
