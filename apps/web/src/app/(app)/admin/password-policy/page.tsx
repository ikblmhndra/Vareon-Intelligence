"use client";

import { AdminFrame } from "@/components/admin/admin-frame";
import { PasswordPolicySection } from "@/components/admin/password-policy-section";

export default function AdminPasswordPolicyPage() {
  return (
    <AdminFrame page="password-policy">
      <PasswordPolicySection />
    </AdminFrame>
  );
}
