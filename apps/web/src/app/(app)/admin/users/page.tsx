"use client";

import { useAuth } from "@/components/providers/auth-provider";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { UsersSection } from "@/components/admin/users-section";
import { RolesSection } from "@/components/admin/roles-section";
import { PasswordPolicySection } from "@/components/admin/password-policy-section";
import { AuditLogSection } from "@/components/admin/audit-log-section";
import { ClientsSection } from "@/components/admin/clients-section";
import { SecretsSection } from "@/components/admin/secrets-section";

/**
 * Port `tab_usermgmt.html`. Role-gate di level HALAMAN (bukan cuma
 * sembunyiin nav item) -- ini `Grup yang beneran punya halaman admin`
 * yang disebut di catatan deferred Grup A. `require_admin`/
 * `require_superadmin` FastAPI tetap enforcement ASLI; ini cuma UI.
 */
export default function AdminUsersPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";

  if (!isAdmin) {
    return (
      <Card className="max-w-md">
        <CardHeader>
          <CardTitle className="font-heading">Admin access required</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Your role ({user?.role}) doesn&apos;t have access to this page.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4 pb-10">
      <UsersSection />
      <RolesSection />
      <PasswordPolicySection />
      <AuditLogSection />
      {user?.role === "superadmin" && <ClientsSection />}
      {user?.role === "superadmin" && <SecretsSection />}
    </div>
  );
}
