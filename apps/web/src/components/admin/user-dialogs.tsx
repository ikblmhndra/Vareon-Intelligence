"use client";

import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { adminErrorMessage, useClients, useRoles } from "@/components/admin/hooks";
import { PasswordRules } from "@/components/password-rules";
import { useAuth } from "@/components/providers/auth-provider";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/lib/api/client";
import type { AdminUser } from "@/lib/api/loose-types";
import { allRulesMet, usePasswordPolicy } from "@/lib/auth/password-policy";
import { unwrap } from "@/lib/scrapers/queries";

/** Fokus kembali ke pemicu menu baris; item menu yang membuka dialog sudah di-unmount. */
function returnFocusTo(username: string | undefined) {
  return () =>
    username ? document.querySelector<HTMLElement>(`[aria-label="Actions for ${CSS.escape(username)}"]`) : null;
}

/** Kerangka dialog: anatomi 6.6 (judul, deskripsi, error `role="alert"`, Cancel + satu tombol utama).
 * Form hanya dimount saat dialog terbuka, jadi state (termasuk password) hilang saat ditutup. */
function DialogShell({
  open,
  onOpenChange,
  title,
  description,
  focusUsername,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  focusUsername?: string;
  children: React.ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm" finalFocus={returnFocusTo(focusUsername)}>
        <DialogHeader>
          <DialogTitle className="font-heading">{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {open && children}
      </DialogContent>
    </Dialog>
  );
}

/** Submit tanpa `useMutation`: password dibaca dari closure dan tidak pernah masuk `variables`/cache. */
function useSubmit(
  permission: string,
  fallback: string,
  run: (fallback: string) => Promise<string>,
  onDone: () => void,
) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      const message = await run(fallback);
      await queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success(message);
      onDone();
    } catch (err) {
      // 403 membawa alasan spesifik server (klien asing, superadmin); kalimat permission hanya bila kosong.
      const detail = err instanceof Error && err.message !== fallback ? err.message : null;
      setError(detail ?? adminErrorMessage(err, permission));
      setPending(false);
    }
  }
  return { pending, error, submit };
}

function Footer({ pending, pendingLabel, label, disabled, onCancel }: {
  pending: boolean;
  pendingLabel: string;
  label: string;
  disabled: boolean;
  onCancel: () => void;
}) {
  return (
    <DialogFooter>
      <Button type="button" variant="outline" onClick={onCancel}>
        Cancel
      </Button>
      <Button type="submit" disabled={pending || disabled}>
        {pending ? pendingLabel : label}
      </Button>
    </DialogFooter>
  );
}

function ErrorNotice({ error }: { error: string | null }) {
  return error ? (
    <div role="alert">
      <Notice tone="destructive" title={error} />
    </div>
  ) : null;
}

/** Role yang boleh dipilih viewer: `superadmin` hanya untuk superadmin. */
function useRoleOptions() {
  const roles = useRoles();
  const { user: me } = useAuth();
  const list = (roles.data ?? []).filter((r) => me?.role === "superadmin" || r.name !== "superadmin");
  const items = Object.fromEntries(
    list.map((r) => [r.name, r.display_name !== r.name ? `${r.name} — ${r.display_name}` : r.name]),
  );
  return { list, items };
}

function RoleSelect({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) {
  const { list, items } = useRoleOptions();
  return (
    <Select items={items} value={value} onValueChange={(v) => v && onChange(v)}>
      <SelectTrigger id={id} className="w-full font-code text-sm">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {list.map((r) => (
          <SelectItem key={r.name} value={r.name} className="font-code text-sm">
            {items[r.name]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Daftar client yang boleh dipilih viewer (P14): superadmin semua, lainnya hanya `client_ids` sendiri. */
function ClientChecklist({
  selected,
  onToggle,
}: {
  selected: Set<string>;
  onToggle: (id: string) => void;
}) {
  const clients = useClients();
  const { user: me } = useAuth();
  const own = me?.role === "superadmin" ? null : new Set(me?.client_ids ?? []);
  const list = (clients.data ?? []).filter((c) => own === null || own.has(c.client_id));

  if (clients.isPending) return <p className="text-xs text-muted-foreground">Loading clients…</p>;
  if (clients.isError)
    return <p className="text-xs text-destructive-text">{adminErrorMessage(clients.error, "manage_users")}</p>;
  // Client yang dipegang target tapi di luar jangkauan viewer: tetap tercentang, tak bisa diubah.
  const hidden = (clients.data ?? []).filter((c) => !list.includes(c) && selected.has(c.client_id));
  return (
    <div role="group" aria-label="Clients" className="flex max-h-52 flex-col gap-1 overflow-y-auto">
      {hidden.map((c) => (
        <label key={c.client_id} className="flex items-center gap-2 py-0.5 text-sm opacity-70">
          <Checkbox checked disabled />
          <span className="text-foreground">{c.name}</span>
          <span className="font-code text-xs text-muted-foreground">{c.client_id}</span>
        </label>
      ))}
      {hidden.length > 0 && (
        <p className="text-xs text-muted-foreground">Assigned by another administrator; you cannot change it.</p>
      )}
      {list.map((c) => (
        <label key={c.client_id} className="flex cursor-pointer items-center gap-2 py-0.5 text-sm">
          <Checkbox checked={selected.has(c.client_id)} onCheckedChange={() => onToggle(c.client_id)} />
          <span className="text-foreground">{c.name}</span>
          <span className="font-code text-xs text-muted-foreground">{c.client_id}</span>
        </label>
      ))}
    </div>
  );
}

function toggled(set: Set<string>, id: string): Set<string> {
  const next = new Set(set);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

export function AddUserDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      title="Add user"
      description="The account can sign in right away with this password."
    >
      <AddUserForm onClose={() => onOpenChange(false)} />
    </DialogShell>
  );
}

function AddUserForm({ onClose }: { onClose: () => void }) {
  const policy = usePasswordPolicy();
  const { user: me } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("analyst");
  const [clientIds, setClientIds] = useState<Set<string>>(() => {
    const own = me?.client_ids ?? [];
    return new Set(me?.role === "superadmin" || own.includes("default") ? ["default"] : own.slice(0, 1));
  });

  const name = username.trim();
  const { pending, error, submit } = useSubmit(
    "manage_users",
    "Could not add the user",
    async (fb) => {
      unwrap(
        await api.POST("/api/auth/users", {
          body: { username: name, password, role, client_ids: Array.from(clientIds) },
        }),
        fb,
      );
      return `${name} added`;
    },
    onClose,
  );

  return (
    <form onSubmit={submit} className="grid gap-4">
      <ErrorNotice error={error} />
      <div className="space-y-1.5">
        <Label htmlFor="add-user-username" className="text-sm font-medium text-muted-foreground">
          Username
        </Label>
        <Input
          id="add-user-username"
          autoComplete="off"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="font-code text-sm"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="add-user-password" className="text-sm font-medium text-muted-foreground">
          Password
        </Label>
        <Input
          id="add-user-password"
          type="password"
          autoComplete="new-password"
          aria-describedby="add-user-rules"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="font-code text-sm"
        />
        <PasswordRules id="add-user-rules" password={password} policy={policy} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="add-user-role" className="text-sm font-medium text-muted-foreground">
          Role
        </Label>
        <RoleSelect id="add-user-role" value={role} onChange={setRole} />
      </div>
      <div className="space-y-1.5">
        <p className="text-sm font-medium text-muted-foreground">Clients</p>
        <ClientChecklist selected={clientIds} onToggle={(id) => setClientIds((s) => toggled(s, id))} />
      </div>
      <Footer
        pending={pending}
        pendingLabel="Adding…"
        label="Add user"
        disabled={name.length < 2 || name.length > 50 || !allRulesMet(password, policy) || clientIds.size === 0}
        onCancel={onClose}
      />
    </form>
  );
}

export function ResetPasswordDialog({
  target,
  onOpenChange,
}: {
  target: AdminUser | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <DialogShell
      open={target !== null}
      onOpenChange={onOpenChange}
      title={`Reset password for ${target?.username ?? ""}?`}
      description="They are signed out everywhere and must choose a new password at their next sign-in."
      focusUsername={target?.username}
    >
      {target && <ResetPasswordForm target={target} onClose={() => onOpenChange(false)} />}
    </DialogShell>
  );
}

function ResetPasswordForm({ target, onClose }: { target: AdminUser; onClose: () => void }) {
  const policy = usePasswordPolicy();
  const [pw, setPw] = useState("");
  const { pending, error, submit } = useSubmit(
    "reset_password",
    "Could not reset the password",
    async (fb) => {
      unwrap(
        await api.POST("/api/auth/users/{username}/reset-password", {
          params: { path: { username: target.username } },
          body: { new_password: pw },
        }),
        fb,
      );
      return `${target.username} must choose a new password at next sign-in`;
    },
    onClose,
  );

  return (
    <form onSubmit={submit} className="grid gap-4">
      <ErrorNotice error={error} />
      <div className="space-y-1.5">
        <Label htmlFor="reset-user-password" className="text-sm font-medium text-muted-foreground">
          Temporary password
        </Label>
        <Input
          id="reset-user-password"
          type="password"
          autoComplete="new-password"
          aria-describedby="reset-user-rules"
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          className="font-code text-sm"
        />
        <PasswordRules id="reset-user-rules" password={pw} policy={policy} />
      </div>
      <Footer
        pending={pending}
        pendingLabel="Resetting…"
        label="Reset password"
        disabled={!allRulesMet(pw, policy)}
        onCancel={onClose}
      />
    </form>
  );
}

export function ChangeRoleDialog({
  target,
  onOpenChange,
}: {
  target: AdminUser | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <DialogShell
      open={target !== null}
      onOpenChange={onOpenChange}
      title={`Change role for ${target?.username ?? ""}`}
      description="Changing the role signs the user out."
      focusUsername={target?.username}
    >
      {target && <ChangeRoleForm target={target} onClose={() => onOpenChange(false)} />}
    </DialogShell>
  );
}

function ChangeRoleForm({ target, onClose }: { target: AdminUser; onClose: () => void }) {
  const [role, setRole] = useState(target.role);
  const { pending, error, submit } = useSubmit(
    "manage_users",
    "Could not change the role",
    async (fb) => {
      unwrap(
        await api.PUT("/api/auth/users/{username}/role", {
          params: { path: { username: target.username } },
          body: { role },
        }),
        fb,
      );
      return `${target.username} is now ${role}`;
    },
    onClose,
  );

  return (
    <form onSubmit={submit} className="grid gap-4">
      <ErrorNotice error={error} />
      <div className="space-y-1.5">
        <Label htmlFor="change-role-select" className="text-sm font-medium text-muted-foreground">
          Role
        </Label>
        <RoleSelect id="change-role-select" value={role} onChange={setRole} />
      </div>
      <Footer pending={pending} pendingLabel="Saving…" label="Save role" disabled={false} onCancel={onClose} />
    </form>
  );
}

export function EditClientsDialog({
  target,
  onOpenChange,
}: {
  target: AdminUser | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <DialogShell
      open={target !== null}
      onOpenChange={onOpenChange}
      title={`Clients for ${target?.username ?? ""}`}
      description="Changing clients signs the user out."
      focusUsername={target?.username}
    >
      {target && <EditClientsForm target={target} onClose={() => onOpenChange(false)} />}
    </DialogShell>
  );
}

function EditClientsForm({ target, onClose }: { target: AdminUser; onClose: () => void }) {
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(target.client_ids.length ? target.client_ids : ["default"]),
  );
  const { pending, error, submit } = useSubmit(
    "manage_users",
    "Could not update the clients",
    async (fb) => {
      unwrap(
        await api.PUT("/api/auth/users/{username}/clients", {
          params: { path: { username: target.username } },
          body: { client_ids: Array.from(selected) },
        }),
        fb,
      );
      return `Clients updated for ${target.username}`;
    },
    onClose,
  );

  return (
    <form onSubmit={submit} className="grid gap-4">
      <ErrorNotice error={error} />
      <ClientChecklist selected={selected} onToggle={(id) => setSelected((s) => toggled(s, id))} />
      <Footer
        pending={pending}
        pendingLabel="Saving…"
        label="Save clients"
        disabled={selected.size === 0}
        onCancel={onClose}
      />
    </form>
  );
}
