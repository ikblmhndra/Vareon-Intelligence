"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ConfirmDialog } from "@/components/confirm-dialog";

const QUERY_KEY = ["xintel", "accounts"] as const;

function useAccounts() {
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/monitored-accounts");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return data;
    },
  });
}

/** Port sub-tab Monitored Accounts. Mutasi (add/remove/toggle) butuh
 * `require_admin` di backend -- form/tombol tetap tampil ke semua user
 * (port apa adanya, sama asimetri kayak kode lama), backend yang nolak
 * kalau bukan admin. */
export function MonitoredAccounts() {
  const queryClient = useQueryClient();
  const accounts = useAccounts();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [notes, setNotes] = useState("");
  const [removeTarget, setRemoveTarget] = useState<string | null>(null);

  const addMutation = useMutation({
    mutationFn: async () => {
      const { data, response } = await api.POST("/api/monitored-accounts", {
        body: { username: username.trim(), display_name: displayName.trim(), notes: notes.trim() },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${response.status}`);
      }
      return data;
    },
    onSuccess: () => {
      setUsername("");
      setDisplayName("");
      setNotes("");
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });

  const removeMutation = useMutation({
    mutationFn: async (target: string) => {
      const { response } = await api.DELETE("/api/monitored-accounts/{username}", {
        params: { path: { username: target } },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
  });

  const toggleMutation = useMutation({
    mutationFn: async ({ target, active }: { target: string; active: boolean }) => {
      const { response } = await api.PATCH("/api/monitored-accounts/{username}/toggle", {
        params: { path: { username: target } },
        body: { active },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
  });

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-2 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Handle</Label>
          <Input
            placeholder="@username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-40 font-mono text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Display name</Label>
          <Input
            placeholder="optional"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="w-40 font-mono text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Notes</Label>
          <Input
            placeholder="optional"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="w-52 font-mono text-xs"
          />
        </div>
        <Button
          size="sm"
          disabled={!username.trim() || addMutation.isPending}
          onClick={() => addMutation.mutate()}
        >
          + Add Account
        </Button>
        {addMutation.isError && (
          <span className="text-xs text-destructive">{(addMutation.error as Error).message}</span>
        )}
      </div>

      {accounts.isPending && (
        <div className="space-y-1.5">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      )}
      {accounts.isError && <p className="text-sm text-destructive">Failed to load accounts.</p>}
      {accounts.data && accounts.data.length === 0 && (
        <p className="text-sm text-muted-foreground">No accounts monitored yet.</p>
      )}
      {accounts.data && accounts.data.length > 0 && (
        <>
          <Table framed>
            <TableHeader>
              <TableRow>
                <TableHead>Handle</TableHead>
                <TableHead>Display Name</TableHead>
                <TableHead>Notes</TableHead>
                <TableHead>Added</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {accounts.data.map((a) => (
                <TableRow key={a.id}>
                  <TableCell className="font-mono text-xs text-primary">@{a.username}</TableCell>
                  <TableCell className="text-xs">{a.display_name || "—"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{a.notes || "—"}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {a.added_at ? a.added_at.slice(0, 10) : "—"}
                  </TableCell>
                  <TableCell>
                    <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
                      <Checkbox
                        checked={a.active}
                        onCheckedChange={(checked) =>
                          toggleMutation.mutate({ target: a.username, active: checked === true })
                        }
                      />
                      Active
                    </label>
                  </TableCell>
                  <TableCell>
                    <Button size="sm" variant="destructive" onClick={() => setRemoveTarget(a.username)}>
                      Remove
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-2.5 font-mono text-xs text-muted-foreground">
            {accounts.data.length} account{accounts.data.length !== 1 ? "s" : ""} monitored
          </p>
        </>
      )}

      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title="Remove monitored account"
        description={`Remove @${removeTarget} from monitored accounts?`}
        confirmLabel="Remove"
        onConfirm={() => removeTarget && removeMutation.mutate(removeTarget)}
      />
    </div>
  );
}
