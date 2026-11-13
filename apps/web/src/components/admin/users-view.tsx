"use client";

import { useMemo, useState } from "react";

import { AdminFrame } from "@/components/admin/admin-frame";
import {
  AddUserDialog,
  ChangeRoleDialog,
  EditClientsDialog,
  ResetPasswordDialog,
} from "@/components/admin/user-dialogs";
import { UsersMiniCards, UsersTiles } from "@/components/admin/users-overview";
import { useAuditExport } from "@/lib/admin/audit-export";
import { useAdminUsers, useClients, useRoles, adminErrorMessage } from "@/components/admin/hooks";
import { useAuth } from "@/components/providers/auth-provider";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { FilterSelect } from "@/components/ui/filter-select";
import { NumberedPager } from "@/components/ui/numbered-pager";
import { RowMenu } from "@/components/ui/row-menu";
import { SearchInput } from "@/components/ui/search-input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { AdminUser } from "@/lib/api/loose-types";
import { userStatus } from "@/lib/admin/user-status";
import { useCan } from "@/lib/auth/permissions";
import { fmtAgo, fmtDateTime, fmtShortDate } from "@/lib/format";

const PAGE_SIZE = 10;

type StatusFilter = "active" | "reset" | "all";
const STATUS_OPTIONS = [
  { value: "active", label: "Active" },
  { value: "reset", label: "Reset pending" },
  { value: "all", label: "All" },
] as const;

function StatusChip({ user }: { user: AdminUser }) {
  const s = userStatus(user);
  if (s === "reset-pending") return <Chip kind="status" value="watch">Reset pending</Chip>;
  if (s === "never") return <Chip kind="flag" value="never">Never signed in</Chip>;
  return <Chip kind="status" value="ok">Active</Chip>;
}

function ClientCell({ user }: { user: AdminUser }) {
  const all = user.client_ids.join(", ");
  if (user.role === "superadmin") {
    return (
      <span title={all || undefined}>
        <Chip kind="flag" value="all">All clients</Chip>
      </span>
    );
  }
  const ids = user.client_ids.length ? user.client_ids : ["default"];
  return (
    <div className="flex items-center gap-1" title={all || undefined}>
      {ids.slice(0, 2).map((c) => (
        <Chip key={c} kind="flag" value={c} className="font-code normal-case">
          {c}
        </Chip>
      ))}
      {ids.length > 2 && <span className="text-xs text-muted-foreground">+{ids.length - 2}</span>}
    </div>
  );
}

/** Kartu Users: filter dalam memori, tabel `table-fixed` 10 baris per halaman, menu aksi per baris. */
function UsersCard({
  onReset,
  onRole,
  onClients,
}: {
  onReset: (u: AdminUser) => void;
  onRole: (u: AdminUser) => void;
  onClients: (u: AdminUser) => void;
}) {
  const can = useCan();
  const { user: me } = useAuth();
  const canManage = can("manage_users");
  const users = useAdminUsers(canManage);
  const roles = useRoles(canManage);
  const clients = useClients(canManage);
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("all");
  const [client, setClient] = useState("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [page, setPage] = useState(1);

  const rows = users.data?.users;
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (rows ?? []).filter((u) => {
      if (q && !u.username.toLowerCase().includes(q)) return false;
      if (role !== "all" && u.role !== role) return false;
      if (client !== "all" && !u.client_ids.includes(client)) return false;
      const s = userStatus(u);
      if (status === "active" && s !== "active") return false;
      if (status === "reset" && s !== "reset-pending") return false;
      return true;
    });
  }, [rows, search, role, client, status]);

  // Ubah filter apa pun kembali ke halaman 1 (setter ini dipanggil dari handler, bukan efek).
  const change = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setPage(1);
  };
  const clearFilters = () => {
    setSearch("");
    setRole("all");
    setClient("all");
    setStatus("all");
    setPage(1);
  };

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const current = Math.min(page, totalPages);
  const from = (current - 1) * PAGE_SIZE;
  const visible = filtered.slice(from, from + PAGE_SIZE);
  const nowMs = users.data?.nowMs ?? 0;

  let body;
  if (!canManage) {
    body = <StatePanel variant="no-access" title="You need the manage_users permission to see users" />;
  } else if (users.isPending) {
    body = (
      <div role="status">
        <Skeleton aria-hidden className="h-64 w-full" />
        <span className="sr-only">Loading users</span>
      </div>
    );
  } else if (users.isError) {
    body =
      (users.error as Error).cause === 403 ? (
        <StatePanel variant="no-access" title={adminErrorMessage(users.error, "manage_users")} />
      ) : (
        <StatePanel
          variant="error"
          title="Failed to load users"
          action={<Button variant="outline" size="sm" onClick={() => void users.refetch()}>Retry</Button>}
        />
      );
  } else if (filtered.length === 0) {
    body = (
      <StatePanel
        variant="empty"
        title="No user matches these filters"
        action={<Button variant="outline" size="sm" onClick={clearFilters}>Clear filters</Button>}
      />
    );
  } else {
    body = (
      <>
        <Table framed className="table-fixed">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-[24%]">User</TableHead>
              <TableHead className="w-[14%]">Role</TableHead>
              <TableHead className="w-[20%]">Client</TableHead>
              <TableHead className="w-[12%]">Created</TableHead>
              <TableHead className="w-[14%]">Last sign in</TableHead>
              <TableHead className="w-[12%]">Status</TableHead>
              <TableHead className="w-[4%]">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {visible.map((u) => {
              const locked = u.role === "superadmin" && me?.role !== "superadmin"; // P15
              return (
                <TableRow key={u.username}>
                  <TableCell>
                    <div className="flex min-w-0 items-center gap-2">
                      <Avatar size="sm" aria-hidden>
                        <AvatarFallback>{u.username.slice(0, 2).toUpperCase()}</AvatarFallback>
                      </Avatar>
                      <span className="truncate font-code text-sm text-foreground">{u.username}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    {u.role === "superadmin" ? (
                      <Chip kind="status" value="watch" className="font-code normal-case">{u.role}</Chip>
                    ) : (
                      <Chip kind="flag" value={u.role} className="font-code normal-case" />
                    )}
                  </TableCell>
                  <TableCell>
                    <ClientCell user={u} />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{fmtShortDate(u.created_at)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    <span title={u.last_sign_in ? fmtDateTime(u.last_sign_in) : undefined}>
                      {u.last_sign_in ? fmtAgo(u.last_sign_in, nowMs) : "–"}
                    </span>
                  </TableCell>
                  <TableCell>
                    <StatusChip user={u} />
                  </TableCell>
                  <TableCell>
                    {!locked && (
                      <RowMenu
                        label={`Actions for ${u.username}`}
                        items={[
                          { label: "Reset password", onSelect: () => onReset(u), hidden: !can("reset_password") },
                          { label: "Change role", onSelect: () => onRole(u), hidden: !canManage },
                          { label: "Edit clients", onSelect: () => onClients(u), hidden: !canManage },
                        ]}
                      />
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        <NumberedPager
          page={current}
          totalPages={totalPages}
          onPageChange={setPage}
          label="Users pagination"
          summary={`Showing ${from + 1}-${from + visible.length} of ${filtered.length}`}
        />
        <p className="pt-1 text-xs text-muted-foreground">
          ⋯ › Reset password makes the user choose a new one at next sign-in
        </p>
      </>
    );
  }

  const roleOptions = [
    { value: "all", label: "All roles" },
    ...(roles.data ?? []).map((r) => ({ value: r.name, label: r.name })),
  ];
  const clientOptions = [
    { value: "all", label: "All clients" },
    ...(clients.data ?? []).map((c) => ({ value: c.client_id, label: c.name })),
  ];

  return (
    <section aria-labelledby="users-card-title" className="rounded-2xl surface-raised p-5">
      <h3 id="users-card-title" className="font-heading text-base font-bold text-foreground">Users</h3>
      <p className="mb-4 text-sm text-muted-foreground">Who can sign in, what they can see, and for which client</p>
      {canManage && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <SearchInput
            value={search}
            onChange={change(setSearch)}
            placeholder="Search username…"
            aria-label="Search username"
            className="w-56"
          />
          <FilterSelect prefix="Role" aria-label="Role" value={role} onChange={change(setRole)} options={roleOptions} />
          <FilterSelect prefix="Client" aria-label="Client" value={client} onChange={change(setClient)} options={clientOptions} />
          <SegmentedControl
            aria-label="User status"
            size="sm"
            options={STATUS_OPTIONS}
            value={status}
            onChange={change(setStatus)}
          />
        </div>
      )}
      {body}
    </section>
  );
}

export function UsersView() {
  const can = useCan();
  const exp = useAuditExport();
  const [addOpen, setAddOpen] = useState(false);
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
  const [roleTarget, setRoleTarget] = useState<AdminUser | null>(null);
  const [clientsTarget, setClientsTarget] = useState<AdminUser | null>(null);

  return (
    <AdminFrame
      page="users"
      headerActions={
        <div className="flex flex-wrap items-center gap-2">
          {can("view_audit_log") && (
            <Button
              variant="outline"
              disabled={exp.pending}
              onClick={() => exp.run({ user: "", action: "" })}
            >
              {exp.pending ? (exp.label ?? "Exporting…") : "Export audit log"}
            </Button>
          )}
          {can("manage_users") && <Button onClick={() => setAddOpen(true)}>+ Add user</Button>}
        </div>
      }
    >
      <UsersTiles />
      <UsersCard onReset={setResetTarget} onRole={setRoleTarget} onClients={setClientsTarget} />
      <UsersMiniCards />
      <AddUserDialog open={addOpen} onOpenChange={setAddOpen} />
      <ResetPasswordDialog target={resetTarget} onOpenChange={(o) => !o && setResetTarget(null)} />
      <ChangeRoleDialog target={roleTarget} onOpenChange={(o) => !o && setRoleTarget(null)} />
      <EditClientsDialog target={clientsTarget} onOpenChange={(o) => !o && setClientsTarget(null)} />
    </AdminFrame>
  );
}
