"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { AdminFrame, AdminPageHeading } from "@/components/admin/admin-frame";
import { adminErrorMessage, useAdminUsers, usePermissions, useRoles } from "@/components/admin/hooks";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Chip } from "@/components/ui/chip";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Notice } from "@/components/ui/notice";
import { RowMenu } from "@/components/ui/row-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { groupPermissions } from "@/lib/admin/permission-groups";
import { api } from "@/lib/api/client";
import type { Role } from "@/lib/api/loose-types";
import { useCan } from "@/lib/auth/permissions";
import { unwrap } from "@/lib/scrapers/queries";

const COL_PERMISSION = 220;
const COL_ALLOWS = 320;
const COL_ROLE = 112;
const ROLE_RE = /^[a-z0-9_-]{2,40}$/;

/** Kolom matriks: semua role kecuali superadmin; role sistem dulu (admin, analyst), lalu custom menurut nama. */
function matrixRoles(roles: Role[]): Role[] {
  return roles
    .filter((r) => r.name !== "superadmin")
    .sort((a, b) => Number(b.is_system) - Number(a.is_system) || a.name.localeCompare(b.name));
}

function Matrix({ roles, onDelete }: { roles: Role[]; onDelete: (r: Role) => void }) {
  const can = useCan();
  const perms = usePermissions();
  const groups = useMemo(() => groupPermissions(perms.data ?? []), [perms.data]);
  const cols = matrixRoles(roles);

  if (perms.isPending) {
    return (
      <div role="status">
        <Skeleton aria-hidden className="h-64 w-full" />
        <span className="sr-only">Loading permissions</span>
      </div>
    );
  }
  if (perms.isError) {
    return (
      <StatePanel
        variant="error"
        title="Failed to load permissions"
        action={<Button variant="outline" size="sm" onClick={() => void perms.refetch()}>Retry</Button>}
      />
    );
  }

  return (
    <>
      <Table
        framed
        className="table-fixed"
        style={{ minWidth: COL_PERMISSION + COL_ALLOWS + COL_ROLE * cols.length }}
      >
        <colgroup>
          <col style={{ width: COL_PERMISSION }} />
          <col style={{ width: COL_ALLOWS }} />
          {cols.map((r) => (
            <col key={r.name} style={{ width: COL_ROLE }} />
          ))}
        </colgroup>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Permission</TableHead>
            <TableHead>Allows</TableHead>
            {cols.map((r) => (
              <TableHead key={r.name} className="align-top">
                <div className="flex items-start justify-between gap-1">
                  <div className="min-w-0">
                    <div className="truncate font-code text-sm text-foreground" title={r.name}>
                      {r.name}
                    </div>
                    <div className="truncate text-xs font-normal text-muted-foreground" title={r.display_name}>
                      {r.display_name}
                    </div>
                    {r.is_system && (
                      <Chip kind="flag" value="SYSTEM" className="mt-1">
                        SYSTEM
                      </Chip>
                    )}
                  </div>
                  {!r.is_system && (
                    <RowMenu
                      label={`Actions for ${r.name}`}
                      items={[
                        {
                          label: "Delete role",
                          destructive: true,
                          onSelect: () => onDelete(r),
                          hidden: !can("manage_roles"),
                        },
                      ]}
                    />
                  )}
                </div>
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {groups.map((g) => (
            <GroupRows key={g.heading} heading={g.heading} span={2 + cols.length}>
              {g.items.map((p) => (
                <TableRow key={p.key}>
                  <TableHead scope="row" className="font-code text-xs font-normal text-foreground">
                    {p.key}
                  </TableHead>
                  <TableCell className="whitespace-normal text-xs text-muted-foreground">
                    {p.description}
                  </TableCell>
                  {cols.map((r) => (
                    <TableCell key={r.name} className="text-center">
                      {r.permissions.includes(p.key) ? (
                        <>
                          <span aria-hidden className="text-success-text">✓</span>
                          <span className="sr-only">allowed</span>
                        </>
                      ) : (
                        <span className="sr-only">not allowed</span>
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </GroupRows>
          ))}
        </TableBody>
      </Table>
      <p className="pt-2 text-xs text-muted-foreground">
        {(perms.data ?? []).length} permissions in total. superadmin is not editable and passes every check.
      </p>
    </>
  );
}

function GroupRows({ heading, span, children }: { heading: string; span: number; children: React.ReactNode }) {
  return (
    <>
      <TableRow className="hover:bg-transparent">
        <TableHead colSpan={span} scope="colgroup" className="text-2xs tracking-wide text-muted-foreground">
          {heading}
        </TableHead>
      </TableRow>
      {children}
    </>
  );
}

function NewRoleDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading">New role</DialogTitle>
          <DialogDescription>A role cannot be edited later; delete it and create it again.</DialogDescription>
        </DialogHeader>
        {open && <NewRoleForm onClose={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}

function NewRoleForm({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const perms = usePermissions();
  const groups = useMemo(() => groupPermissions(perms.data ?? []), [perms.data]);
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const idOk = ROLE_RE.test(name);
  const displayOk = displayName.trim().length >= 1 && displayName.trim().length <= 60;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      unwrap(
        await api.POST("/api/roles", {
          body: { name, display_name: displayName.trim(), permissions: Array.from(selected) },
        }),
        "Could not create the role",
      );
      await queryClient.invalidateQueries({ queryKey: ["admin", "roles"] });
      toast.success(`Role ${name} created`);
      onClose();
    } catch (err) {
      setError(adminErrorMessage(err, "manage_roles"));
      setPending(false);
    }
  }

  function toggle(key: string) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <form onSubmit={submit} className="grid gap-4">
      {error && (
        <div role="alert">
          <Notice tone="destructive" title={error} />
        </div>
      )}
      <div className="space-y-1.5">
        <Label htmlFor="new-role-id" className="text-sm font-medium text-muted-foreground">
          Role ID
        </Label>
        <Input
          id="new-role-id"
          autoComplete="off"
          value={name}
          aria-invalid={name !== "" && !idOk}
          aria-describedby="new-role-id-help"
          onChange={(e) => setName(e.target.value)}
          className="font-code text-sm"
        />
        <p
          id="new-role-id-help"
          className={`text-xs ${name !== "" && !idOk ? "text-destructive-text" : "text-muted-foreground"}`}
        >
          2-40 characters: a-z, 0-9, _ or -
        </p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="new-role-display" className="text-sm font-medium text-muted-foreground">
          Display name
        </Label>
        <Input
          id="new-role-display"
          maxLength={60}
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          className="text-sm"
        />
      </div>
      <div className="space-y-1.5">
        <p className="text-sm font-medium text-muted-foreground">Permissions</p>
        {perms.isPending && <Skeleton className="h-24 w-full" />}
        {perms.isError && (
          <p className="text-xs text-destructive-text">{adminErrorMessage(perms.error, "manage_roles")}</p>
        )}
        <div className="flex max-h-64 flex-col gap-3 overflow-y-auto rounded-md border border-border p-2">
          {groups.map((g) => (
            <div key={g.heading} role="group" aria-label={g.heading} className="flex flex-col gap-1.5">
              <p className="text-2xs font-semibold tracking-wide text-muted-foreground">{g.heading}</p>
              {g.items.map((p) => (
                <label key={p.key} className="flex cursor-pointer items-start gap-2 text-sm">
                  <Checkbox
                    className="mt-0.5"
                    checked={selected.has(p.key)}
                    onCheckedChange={() => toggle(p.key)}
                  />
                  <span>
                    <span className="font-code text-xs text-foreground">{p.key}</span>
                    <br />
                    <span className="text-xs text-muted-foreground">{p.description}</span>
                  </span>
                </label>
              ))}
            </div>
          ))}
        </div>
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending || !idOk || !displayOk}>
          {pending ? "Creating…" : "Create role"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function DeleteRoleDialog({ target, onClose }: { target: Role | null; onClose: () => void }) {
  const can = useCan();
  const queryClient = useQueryClient();
  const canSeeUsers = can("manage_users");
  // Query dibuat hanya bila viewer boleh membaca users; tanpa itu API yang menolak (FK users.role_name).
  // Hanya selama ada target: dialog tertutup tak perlu memuat daftar user.
  const users = useAdminUsers(canSeeUsers && target !== null);
  const [pending, setPending] = useState(false);
  // Nama bertahan selama animasi tutup (target sudah null), supaya judul tak jadi "Delete role ?".
  const [shown, setShown] = useState(target);
  if (target && target !== shown) setShown(target);

  const name = target?.name ?? shown?.name ?? "";
  const n = users.data ? users.data.users.filter((u) => u.role === name).length : 0;
  const blocked = n > 0 || (canSeeUsers && users.isPending);

  async function confirm() {
    setPending(true);
    try {
      unwrap(
        await api.DELETE("/api/roles/{name}", { params: { path: { name } } }),
        "Could not delete the role",
      );
      await queryClient.invalidateQueries({ queryKey: ["admin", "roles"] });
      toast.success(`Role ${name} deleted`);
      onClose();
    } catch (err) {
      // 500 polos = FK users.role_name masih menunjuk role ini; "Internal Server Error" mentah tak berguna.
      toast.error(
        err instanceof Error && typeof err.cause === "number" && err.cause >= 500
          ? "Could not delete the role. It may still be assigned to users."
          : adminErrorMessage(err, "manage_roles"),
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <ConfirmDialog
      open={target !== null}
      onOpenChange={(o) => !o && onClose()}
      tone="danger"
      title={`Delete role ${name}?`}
      description={
        n > 0
          ? `${n} ${n === 1 ? "user has" : "users have"} this role. Move them to another role first.`
          : "The role is removed. This cannot be undone."
      }
      confirmLabel="Delete role"
      confirmLoading={pending}
      confirmDisabled={blocked}
      onConfirm={() => void confirm()}
    />
  );
}

/** Halaman Roles: matriks izin baca-saja; "New role" dan "Delete role" dijaga `manage_roles` seperti di API. */
export function RolesView() {
  const can = useCan();
  const roles = useRoles();
  const [newOpen, setNewOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null);

  let body;
  if (roles.isPending) {
    body = (
      <div role="status">
        <Skeleton aria-hidden className="h-64 w-full" />
        <span className="sr-only">Loading roles</span>
      </div>
    );
  } else if (roles.isError) {
    body = (
      <StatePanel
        variant="error"
        title="Failed to load roles"
        action={<Button variant="outline" size="sm" onClick={() => void roles.refetch()}>Retry</Button>}
      />
    );
  } else {
    body = <Matrix roles={roles.data} onDelete={setDeleteTarget} />;
  }

  return (
    <AdminFrame page="roles">
      <AdminPageHeading
        title="Roles"
        description="What each role is allowed to do. Roles are created and deleted, not edited."
        action={
          can("manage_roles") ? <Button onClick={() => setNewOpen(true)}>+ New role</Button> : undefined
        }
      />
      {body}
      {can("manage_roles") && <NewRoleDialog open={newOpen} onOpenChange={setNewOpen} />}
      <DeleteRoleDialog target={deleteTarget} onClose={() => setDeleteTarget(null)} />
    </AdminFrame>
  );
}
