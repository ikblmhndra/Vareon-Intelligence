"use client";

import { useAuth } from "@/components/providers/auth-provider";
import { useCan } from "@/lib/auth/permissions";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { UsersSection } from "@/components/admin/users-section";
import { RolesSection } from "@/components/admin/roles-section";
import { PasswordPolicySection } from "@/components/admin/password-policy-section";
import { AuditLogSection } from "@/components/admin/audit-log-section";
import { ClientsSection } from "@/components/admin/clients-section";
import { ApiTokensSection } from "@/components/admin/api-tokens-section";
import { SecretsSection } from "@/components/admin/secrets-section";

/**
 * Port `tab_usermgmt.html`. Role-gate di level HALAMAN (bukan cuma
 * sembunyiin nav item) -- ini `Grup yang beneran punya halaman admin`
 * yang disebut di catatan deferred Grup A. `require_admin`/
 * `require_superadmin` FastAPI tetap enforcement ASLI; ini cuma UI.
 */
export default function AdminUsersPage() {
  const { user } = useAuth();
  const can = useCan();
  const adminPermissions = ["manage_users", "manage_roles", "manage_policy", "view_audit_log", "manage_clients", "manage_api_tokens"];

  if (!adminPermissions.some(can)) {
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
      {can("manage_users") && <UsersSection />}
      <RolesSection />
      {can("manage_policy") && <PasswordPolicySection />}
      {can("view_audit_log") && <AuditLogSection />}
      {can("manage_clients") && <ClientsSection />}
      {can("manage_api_tokens") && <ApiTokensSection />}
      {/* Secrets tidak punya permission sendiri: API-nya `require_superadmin`. */}
      {user?.role === "superadmin" && <SecretsSection />}
    </div>
  );
}
