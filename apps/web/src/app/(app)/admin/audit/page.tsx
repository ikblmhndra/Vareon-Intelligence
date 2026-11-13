"use client";

import { AdminFrame } from "@/components/admin/admin-frame";
import { AuditLogSection } from "@/components/admin/audit-log-section";

export default function AdminAuditPage() {
  return (
    <AdminFrame page="audit">
      <AuditLogSection />
    </AdminFrame>
  );
}
