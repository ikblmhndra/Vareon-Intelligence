"use client";

import { AdminFrame } from "@/components/admin/admin-frame";
import { UsersSection } from "@/components/admin/users-section";
import { StatePanel } from "@/components/ui/state-panel";
import { useCan } from "@/lib/auth/permissions";

export default function AdminUsersPage() {
  const can = useCan();
  return (
    <AdminFrame page="users">
      {can("manage_users") ? (
        <UsersSection />
      ) : (
        <StatePanel variant="no-access" title="You need the manage_users permission to see users" />
      )}
    </AdminFrame>
  );
}
