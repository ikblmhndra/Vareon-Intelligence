"use client";

import { AdminFrame } from "@/components/admin/admin-frame";
import { SecretsSection } from "@/components/admin/secrets-section";

export default function AdminKeysPage() {
  return (
    <AdminFrame page="keys">
      <SecretsSection />
    </AdminFrame>
  );
}
