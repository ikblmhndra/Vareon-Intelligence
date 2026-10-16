"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { useAuth } from "@/components/providers/auth-provider";
import { policyHint, usePasswordPolicy, validatePasswordClient } from "@/lib/auth/password-policy";
import type { AdminUser } from "@/lib/api/loose-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAdminUsers, useClients, useRoles } from "@/components/admin/hooks";

const USERS_KEY = ["admin", "users"] as const;

function roleBadgeClass(role: string): string {
  if (role === "superadmin") return "border-warning/40 bg-warning/10 text-warning-text";
  if (role === "admin") return "border-ring/40 bg-ring/10 text-primary-text";
  return "border-primary/30 bg-primary/10 text-primary-text";
}

/** Port section "Users" + "Add User" + row action dropdown (⋮) di
 * `tab_usermgmt.html`/`usermgmt.js`. */
export function UsersSection() {
  const { user: me } = useAuth();
  const isAdmin = me?.role === "admin" || me?.role === "superadmin";
  const users = useAdminUsers();
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
  const [roleTarget, setRoleTarget] = useState<AdminUser | null>(null);
  const [clientsTarget, setClientsTarget] = useState<AdminUser | null>(null);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-semibold text-foreground">
          Users
        </CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div>
          {users.isPending && <Skeleton className="h-40 w-full" />}
          {users.isError && <p className="text-sm text-destructive">Failed to load users.</p>}
          {users.data && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Username</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Client</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Last Sign In</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.data.map((u) => (
                  <TableRow key={u.username}>
                    <TableCell className="font-mono text-xs text-foreground">{u.username}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={`font-mono text-xs ${roleBadgeClass(u.role)}`}>
                        {u.role}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {(u.client_ids.length ? u.client_ids : ["default"]).map((c) => (
                          <Badge key={c} variant="outline" className="font-mono text-xs text-muted-foreground">
                            {c}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {u.created_at.split("T")[0]}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {u.last_sign_in ? u.last_sign_in.replace("T", " ").split(".")[0] : "—"}
                    </TableCell>
                    <TableCell>
                      <DropdownMenu>
                        <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" />}>
                          ⋮
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={() => setResetTarget(u)}>Reset Password</DropdownMenuItem>
                          {isAdmin && (
                            <>
                              <DropdownMenuItem onClick={() => setClientsTarget(u)}>Edit Clients</DropdownMenuItem>
                              <DropdownMenuItem onClick={() => setRoleTarget(u)}>Change Role</DropdownMenuItem>
                            </>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>

        <AddUserForm />
      </CardContent>

      {/* `key` per target: remount tiap buka/tutup, jadi role/password yang
          diketik buat user A (lalu Cancel) gak kebawa ke user B. */}
      <ResetPasswordDialog
        key={resetTarget?.username ?? "none"}
        target={resetTarget}
        onOpenChange={(open) => !open && setResetTarget(null)}
      />
      <ChangeRoleDialog
        key={roleTarget?.username ?? "none"}
        target={roleTarget}
        onOpenChange={(open) => !open && setRoleTarget(null)}
      />
      <EditClientsDialog target={clientsTarget} onOpenChange={(open) => !open && setClientsTarget(null)} />
    </Card>
  );
}

function AddUserForm() {
  const queryClient = useQueryClient();
  const roles = useRoles();
  const policy = usePasswordPolicy();
  const { user: me } = useAuth();
  const isSuperadmin = me?.role === "superadmin";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("analyst");
  const [clientIds, setClientIds] = useState("default");
  const [error, setError] = useState<string | null>(null);

  const addMutation = useMutation({
    mutationFn: async () => {
      const ids = clientIds
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const { data, response } = await api.POST("/api/auth/users", {
        body: { username, password, role, client_ids: ids.length ? ids : ["default"] },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        const msg = Array.isArray(body?.detail)
          ? body.detail.map((e: { msg?: string }) => e.msg).join("; ")
          : body?.detail || `HTTP ${response.status}`;
        throw new Error(msg);
      }
      return data;
    },
    onSuccess: () => {
      setUsername("");
      setPassword("");
      void queryClient.invalidateQueries({ queryKey: USERS_KEY });
    },
    onError: (e: Error) => setError(e.message),
  });

  function handleSubmit() {
    setError(null);
    if (!username.trim()) return setError("Username required.");
    if (!password) return setError("Password required.");
    const pwErr = validatePasswordClient(password, policy);
    if (pwErr) return setError(pwErr);
    addMutation.mutate();
  }

  const availableRoles = (roles.data ?? []).filter((r) => isSuperadmin || r.name !== "superadmin");

  return (
    <div>
      <div className="mb-3 text-base font-semibold text-foreground">Add User</div>
      <div className="space-y-2.5">
        <div className="space-y-1.5">
          <Label htmlFor="add-user-username" className="text-sm font-medium text-muted-foreground">Username</Label>
          <Input id="add-user-username" autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} className="font-mono text-xs" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="add-user-password" className="text-sm font-medium text-muted-foreground">
            Password <span className="normal-case">({policyHint(policy)})</span>
          </Label>
          <Input
            id="add-user-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="font-mono text-xs"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-sm font-medium text-muted-foreground">Role</Label>
          <Select value={role} onValueChange={(v) => v && setRole(v)}>
            <SelectTrigger className="w-full font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {availableRoles.map((r) => (
                <SelectItem key={r.name} value={r.name} className="font-mono text-xs">
                  {r.display_name !== r.name ? `${r.name} — ${r.display_name}` : r.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="add-user-clients" className="text-sm font-medium text-muted-foreground">
            Client(s) <span className="normal-case">comma-separated</span>
          </Label>
          <Input id="add-user-clients" value={clientIds} onChange={(e) => setClientIds(e.target.value)} className="font-mono text-xs" />
        </div>
        {error && (
          <p className="rounded-md border border-destructive/30 bg-destructive/10 px-2 py-1.5 text-xs text-destructive-text">
            {error}
          </p>
        )}
        <Button size="sm" onClick={handleSubmit} disabled={addMutation.isPending}>
          Add User
        </Button>
      </div>
    </div>
  );
}

function ResetPasswordDialog({
  target,
  onOpenChange,
}: {
  target: AdminUser | null;
  onOpenChange: (open: boolean) => void;
}) {
  const policy = usePasswordPolicy();
  const [pw, setPw] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      const { response } = await api.POST("/api/auth/users/{username}/reset-password", {
        params: { path: { username: target!.username } },
        body: { new_password: pw },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${response.status}`);
      }
    },
    onSuccess: () => {
      setPw("");
      onOpenChange(false);
    },
    onError: (e: Error) => setError(e.message),
  });

  function handleSubmit() {
    setError(null);
    const pwErr = validatePasswordClient(pw, policy);
    if (pwErr) return setError(pwErr);
    mutation.mutate();
  }

  return (
    <Dialog open={target !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="font-heading">Reset Password</DialogTitle>
        </DialogHeader>
        <p className="font-mono text-xs text-muted-foreground">
          User: <span className="text-foreground">{target?.username}</span>
        </p>
        <div className="space-y-1.5">
          <Label htmlFor="reset-user-password" className="text-sm font-medium text-muted-foreground">
            New Password <span className="normal-case">({policyHint(policy)})</span>
          </Label>
          <Input id="reset-user-password" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} className="font-mono text-xs" />
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={mutation.isPending}>
            Reset
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ChangeRoleDialog({
  target,
  onOpenChange,
}: {
  target: AdminUser | null;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const roles = useRoles();
  const { user: me } = useAuth();
  const isSuperadmin = me?.role === "superadmin";
  const [role, setRole] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      const { response } = await api.PUT("/api/auth/users/{username}/role", {
        params: { path: { username: target!.username } },
        body: { role: role ?? target!.role },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${response.status}`);
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USERS_KEY });
      onOpenChange(false);
      setRole(null);
    },
    onError: (e: Error) => setError(e.message),
  });

  const availableRoles = (roles.data ?? []).filter((r) => isSuperadmin || r.name !== "superadmin");
  const currentValue = role ?? target?.role ?? "";

  return (
    <Dialog open={target !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="font-heading">Change Role</DialogTitle>
        </DialogHeader>
        <p className="font-mono text-xs text-muted-foreground">
          User: <span className="text-foreground">{target?.username}</span>
        </p>
        <Select value={currentValue} onValueChange={(v) => v && setRole(v)}>
          <SelectTrigger className="w-full font-mono text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {availableRoles.map((r) => (
              <SelectItem key={r.name} value={r.name} className="font-mono text-xs">
                {r.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Dibuka programatik (`target` di-set dari dropdown ⋮), jadi
 * `onOpenChange(true)` gak pernah kepanggil -- init `selected` di situ
 * bikin checkbox kebuka kosong (QA BUG-02). Body cuma mount pas `target`
 * ada + `key` per user: state lazy-init dari `target.client_ids`. */
function EditClientsDialog({
  target,
  onOpenChange,
}: {
  target: AdminUser | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={target !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="font-heading">Edit Clients</DialogTitle>
        </DialogHeader>
        {target && <EditClientsForm key={target.username} target={target} onClose={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}

function EditClientsForm({ target, onClose }: { target: AdminUser; onClose: () => void }) {
  const queryClient = useQueryClient();
  const clients = useClients();
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(target.client_ids.length ? target.client_ids : ["default"]),
  );
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      const ids = Array.from(selected);
      const { response } = await api.PUT("/api/auth/users/{username}/clients", {
        params: { path: { username: target.username } },
        body: { client_ids: ids },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${response.status}`);
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USERS_KEY });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  function handleSave() {
    if (selected.size === 0) return setError("At least one client required.");
    mutation.mutate();
  }

  return (
    <>
      <p className="font-mono text-xs text-muted-foreground">
        User: <span className="text-foreground">{target.username}</span>
      </p>
      {clients.isPending && <p className="text-xs text-muted-foreground">Loading…</p>}
      <div className="flex max-h-52 flex-col gap-1 overflow-y-auto">
        {clients.data?.map((c) => (
          <label key={c.client_id} className="flex cursor-pointer items-center gap-2 py-0.5 text-xs">
            <Checkbox checked={selected.has(c.client_id)} onCheckedChange={() => toggle(c.client_id)} />
            <span className="text-foreground">{c.name}</span>
            <span className="font-mono text-xs text-muted-foreground">{c.client_id}</span>
          </label>
        ))}
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={handleSave} disabled={mutation.isPending}>
          Save
        </Button>
      </DialogFooter>
    </>
  );
}
