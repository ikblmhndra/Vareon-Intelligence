"use client";

import type { ReactNode } from "react";

import { SessionCard } from "@/components/admin/session-card";
import { PageHeader } from "@/components/page-header";
import { useAuth } from "@/components/providers/auth-provider";
import { SideNav } from "@/components/ui/side-nav";
import { StatePanel } from "@/components/ui/state-panel";
import { useCan } from "@/lib/auth/permissions";
import { usePageTitle } from "@/lib/use-page-title";

export type AdminPage =
  | "users"
  | "roles"
  | "password-policy"
  | "clients"
  | "tokens"
  | "audit"
  | "keys";

// Gerbang halaman = daftar enam permission halaman Admin lama (A22); API tetap penegak asli.
const ADMIN_PERMISSIONS = [
  "manage_users",
  "manage_roles",
  "manage_policy",
  "view_audit_log",
  "manage_clients",
  "manage_api_tokens",
];

type Gate = (can: (p: string) => boolean, isSuper: boolean) => boolean;
const ALWAYS: Gate = () => true;

const PAGES: Record<
  AdminPage,
  { group: string; label: string; href: string; listed: Gate; need: string }
> = {
  users: { group: "ACCESS", label: "Users", href: "/admin/users", listed: ALWAYS, need: "" },
  roles: { group: "ACCESS", label: "Roles", href: "/admin/roles", listed: ALWAYS, need: "" },
  "password-policy": {
    group: "ACCESS",
    label: "Password policy",
    href: "/admin/password-policy",
    listed: (can) => can("manage_policy"),
    need: "You need the manage_policy permission",
  },
  clients: {
    group: "TENANTS",
    label: "Clients",
    href: "/admin/clients",
    listed: (can) => can("manage_users") || can("manage_clients"),
    need: "You need the manage_users or manage_clients permission",
  },
  tokens: {
    group: "TENANTS",
    label: "API tokens",
    href: "/admin/tokens",
    listed: (can) => can("manage_api_tokens"),
    need: "You need the manage_api_tokens permission",
  },
  audit: {
    group: "SECURITY",
    label: "Audit log",
    href: "/admin/audit",
    listed: (can) => can("view_audit_log"),
    need: "You need the view_audit_log permission",
  },
  keys: {
    group: "SECURITY",
    label: "Third-party keys",
    href: "/admin/keys",
    listed: (_can, isSuper) => isSuper,
    need: "Only a superadmin can manage third-party keys",
  },
};

const GROUPS = ["ACCESS", "TENANTS", "SECURITY"];

/** Judul h2 satu baris untuk keenam halaman selain Users (P16): nama, deskripsi, aksi utama di kanan. */
export function AdminPageHeading({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
      <div className="min-w-0">
        <h2 className="font-heading text-xl font-bold text-foreground">{title}</h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}

/** Kerangka Admin: header tetap, nav samping bergrup (tiap item dijaga permission aslinya) dan kartu sesi. */
export function AdminFrame({
  page,
  headerActions,
  children,
}: {
  page: AdminPage;
  headerActions?: ReactNode;
  children: ReactNode;
}) {
  const { user } = useAuth();
  const can = useCan();
  const current = PAGES[page];
  usePageTitle(`${current.label} · Admin`);

  if (!user) return null;
  if (!ADMIN_PERMISSIONS.some(can)) {
    return (
      <StatePanel
        variant="no-access"
        title="Admin access required"
        description={`Your role (${user.role}) cannot open this page.`}
      />
    );
  }

  const isSuper = user.role === "superadmin";
  const groups = GROUPS.map((heading) => ({
    heading,
    items: Object.values(PAGES).filter((p) => p.group === heading && p.listed(can, isSuper)),
  }));

  return (
    <>
      <PageHeader
        kicker={`ADMINISTRATION · ${user.role.toUpperCase()}`}
        title="Admin"
        description="People, roles, tenants and keys. Every change here is written to the audit log."
        actions={headerActions}
      />
      <div className="grid gap-6 pb-10 lg:grid-cols-[240px_1fr]">
        <aside className="flex flex-col gap-4">
          <SideNav aria-label="Admin sections" groups={groups} />
          <SessionCard />
        </aside>
        <div className="min-w-0">
          {current.listed(can, isSuper) ? (
            children
          ) : (
            <StatePanel variant="no-access" title={current.need} />
          )}
        </div>
      </div>
    </>
  );
}
