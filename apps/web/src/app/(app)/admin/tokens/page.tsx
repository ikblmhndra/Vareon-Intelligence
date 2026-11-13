"use client";

import { AdminFrame } from "@/components/admin/admin-frame";
import { ApiTokensSection } from "@/components/admin/api-tokens-section";

export default function AdminTokensPage() {
  return (
    <AdminFrame page="tokens">
      <ApiTokensSection />
    </AdminFrame>
  );
}
