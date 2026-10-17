"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { useAuth } from "@/components/providers/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { usePermissions, useRoles } from "@/components/admin/hooks";

const ROLES_KEY = ["admin", "roles"] as const;

/** Port section "User Roles" di `tab_usermgmt.html` + `loadUMRoles()`/
 * `umOpenAddRoleModal()`/`umSaveRole()`/`umDeleteRole()`. Add/Delete Role
 * superadmin-only (`require_superadmin` di `routers/roles.py`). */
export function RolesSection() {
  const { user } = useAuth();
  const isSuperadmin = user?.role === "superadmin";
  const queryClient = useQueryClient();
  const roles = useRoles();
  const [addOpen, setAddOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const deleteMutation = useMutation({
    mutationFn: async (name: string) => {
      const { response } = await api.DELETE("/api/roles/{name}", { params: { path: { name } } });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${response.status}`);
      }
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ROLES_KEY }),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-semibold text-foreground">
          User Roles
        </CardTitle>
        {isSuperadmin && (
          <CardAction>
            <Button size="sm" onClick={() => setAddOpen(true)}>
              + Add Role
            </Button>
          </CardAction>
        )}
      </CardHeader>
      <CardContent>
        {roles.isPending && <Skeleton className="h-24 w-full" />}
        {roles.isError && <p className="text-sm text-destructive">Failed to load roles.</p>}
        {roles.data && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Role</TableHead>
                <TableHead>Display Name</TableHead>
                <TableHead>Permissions</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {roles.data.map((r) => (
                <TableRow key={r.name}>
                  <TableCell className="font-mono text-xs text-primary">
                    {r.name}
                    {r.is_system && (
                      <Badge variant="outline" className="ml-1.5 border-ring/30 bg-ring/10 text-xs text-primary-text">
                        system
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">{r.display_name || r.name}</TableCell>
                  <TableCell className="max-w-md">
                    <div className="flex flex-wrap gap-1">
                      {r.permissions.length ? (
                        r.permissions.map((p) => (
                          <Badge key={p} variant="outline" className="font-mono text-xs text-muted-foreground">
                            {p}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-xs text-muted-foreground">no permissions</span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    {isSuperadmin && !r.is_system && (
                      <Button size="sm" variant="destructive" onClick={() => setDeleteTarget(r.name)}>
                        Delete
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <AddRoleDialog open={addOpen} onOpenChange={setAddOpen} />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Delete role"
        description={`Delete role "${deleteTarget}"? Users assigned this role will keep it until manually changed.`}
        confirmLabel="Delete"
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget)}
      />
    </Card>
  );
}

function AddRoleDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const permissions = usePermissions();
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const { data, response } = await api.POST("/api/roles", {
        body: { name, display_name: displayName, permissions: Array.from(selected) },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${response.status}`);
      }
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ROLES_KEY });
      onOpenChange(false);
      setName("");
      setDisplayName("");
      setSelected(new Set());
    },
    onError: (e: Error) => setError(e.message),
  });

  function handleSave() {
    setError(null);
    if (!name.trim()) return setError("Role ID required.");
    if (!displayName.trim()) return setError("Display name required.");
    if (!/^[a-z0-9_-]+$/.test(name)) return setError("Role ID: lowercase a-z, 0-9, _ or - only.");
    saveMutation.mutate();
  }

  function toggle(key: string) {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelected(next);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading">Add Role</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="add-role-id" className="text-sm font-medium text-muted-foreground">
              Role ID (lowercase, a-z 0-9 _-)
            </Label>
            <Input id="add-role-id" value={name} onChange={(e) => setName(e.target.value)} className="font-mono text-xs" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="add-role-display" className="text-sm font-medium text-muted-foreground">Display Name</Label>
            <Input id="add-role-display" value={displayName} onChange={(e) => setDisplayName(e.target.value)} className="text-xs" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-sm font-medium text-muted-foreground">Permissions</Label>
            {permissions.isPending && <Skeleton className="h-24 w-full" />}
            <div className="flex max-h-52 flex-col gap-1.5 overflow-y-auto rounded-md border border-border p-2">
              {permissions.data?.map((p) => (
                <label key={p.key} className="flex cursor-pointer items-start gap-2 text-xs">
                  <Checkbox
                    className="mt-0.5"
                    checked={selected.has(p.key)}
                    onCheckedChange={() => toggle(p.key)}
                  />
                  <span>
                    <span className="font-mono text-foreground">{p.key}</span>
                    <br />
                    <span className="text-xs text-muted-foreground">{p.description}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saveMutation.isPending}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
