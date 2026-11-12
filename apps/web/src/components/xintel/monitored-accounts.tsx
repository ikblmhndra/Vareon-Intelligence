"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { useCan } from "@/lib/auth/permissions";
import { apiErrorMessage } from "@/lib/recap/quality";
import { isClientError } from "@/lib/exec/query";
import { fmtShortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

const QUERY_KEY = ["xintel", "accounts"] as const;

/** Dipakai juga header halaman untuk hitungan tab: satu key, jadi mutasi di sini menyegarkan keduanya. */
export function useAccounts() {
  return useQuery({
    queryKey: QUERY_KEY,
    retry: (n, e) => n < 2 && !isClientError(e),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/monitored-accounts");
      if (!response.ok) throw new Error(`HTTP ${response.status}`, { cause: response.status });
      return data;
    },
  });
}

function failure(error: unknown, response: Response): Error {
  return new Error(apiErrorMessage(error, response.status), { cause: response.status });
}

/** Tab Monitored Accounts. Daftar terbuka untuk `view_tweets`; tulis (tambah/ubah/hapus) butuh `manage_tweets`
 * di backend, jadi kontrolnya hanya aktif untuk izin itu (bukan yang lebih ketat). */
export function MonitoredAccounts() {
  const can = useCan();
  const canManage = can("manage_tweets");
  const queryClient = useQueryClient();
  const accounts = useAccounts();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [notes, setNotes] = useState("");
  const [removeTarget, setRemoveTarget] = useState<string | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: QUERY_KEY });

  const addMutation = useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST("/api/monitored-accounts", {
        body: { username: username.trim(), display_name: displayName.trim(), notes: notes.trim() },
      });
      if (!response.ok) throw failure(error, response);
      return data;
    },
    onSuccess: () => {
      setUsername("");
      setDisplayName("");
      setNotes("");
      refresh();
    },
  });

  const removeMutation = useMutation({
    mutationFn: async (target: string) => {
      const { error, response } = await api.DELETE("/api/monitored-accounts/{username}", {
        params: { path: { username: target } },
      });
      if (!response.ok) throw failure(error, response);
    },
    onSuccess: refresh,
    onError: (e) => toast.error(`Could not remove account: ${e.message}`),
  });

  const toggleMutation = useMutation({
    mutationFn: async ({ target, active }: { target: string; active: boolean }) => {
      const { error, response } = await api.PATCH("/api/monitored-accounts/{username}/toggle", {
        params: { path: { username: target } },
        body: { active },
      });
      if (!response.ok) throw failure(error, response);
    },
    onSuccess: refresh,
    onError: (e) => toast.error(`Could not update account: ${e.message}`),
  });

  const list = accounts.data;
  const activeCount = list?.filter((a) => a.active).length ?? 0;

  return (
    <div>
      {canManage && (
        <form
          className="mb-5 flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (username.trim() && !addMutation.isPending) addMutation.mutate();
          }}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="xi-handle">Handle</Label>
            <Input id="xi-handle" placeholder="@FalconFeedsio" value={username} onChange={(e) => setUsername(e.target.value)} className="w-48 font-code" />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="xi-display-name">Display name</Label>
            <Input id="xi-display-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} className="w-48" />
          </div>
          <div className="flex min-w-48 flex-1 flex-col gap-1">
            <Label htmlFor="xi-notes">Notes (optional)</Label>
            <Input id="xi-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
          <Button type="submit" disabled={!username.trim()} loading={addMutation.isPending}>
            Add account
          </Button>
          {addMutation.isError && (
            <p role="alert" className="basis-full text-xs text-destructive-text">
              {addMutation.error.message}
            </p>
          )}
        </form>
      )}

      {accounts.isPending && (
        <div className="space-y-1.5" role="status" aria-label="Loading accounts">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      )}
      {accounts.isError && (
        <StatePanel
          variant="error"
          title="Failed to load accounts"
          action={
            <Button variant="outline" onClick={() => void accounts.refetch()}>
              Retry
            </Button>
          }
        />
      )}
      {list && list.length === 0 && <StatePanel variant="empty" title="No accounts monitored yet" />}
      {list && list.length > 0 && (
        <>
          <Table framed className="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className="w-[18%]">Handle</TableHead>
                <TableHead className="w-[18%]">Display name</TableHead>
                <TableHead className="w-[30%]">Notes</TableHead>
                <TableHead className="w-[12%]">Added</TableHead>
                <TableHead className="w-[10%]">Active</TableHead>
                <TableHead className="w-[12%]">
                  <span className="sr-only">Remove</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((a) => (
                <TableRow key={a.id} className={cn(!a.active && "text-muted-foreground")}>
                  <TableCell className="truncate font-code text-xs">@{a.username}</TableCell>
                  <TableCell className="truncate text-xs">{a.display_name || "—"}</TableCell>
                  <TableCell className="truncate text-xs text-muted-foreground">{a.notes || "—"}</TableCell>
                  <TableCell className="font-code text-xs text-muted-foreground">{fmtShortDate(a.added_at)}</TableCell>
                  <TableCell>
                    <Switch
                      aria-label={`Active: @${a.username}`}
                      checked={a.active}
                      disabled={!canManage || toggleMutation.isPending}
                      onCheckedChange={(active) => toggleMutation.mutate({ target: a.username, active })}
                    />
                  </TableCell>
                  <TableCell>
                    {canManage && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-destructive-text"
                        aria-label={`Remove @${a.username}`}
                        onClick={() => setRemoveTarget(a.username)}
                      >
                        Remove
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-2.5 text-xs text-muted-foreground">
            <span className="font-code">{list.length}</span> accounts monitored · <span className="font-code">{activeCount}</span> active
          </p>
        </>
      )}

      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title="Remove monitored account"
        description={`Remove @${removeTarget} from monitored accounts? Its posts stay in the feed.`}
        confirmLabel="Remove"
        tone="danger"
        onConfirm={() => removeTarget && removeMutation.mutate(removeTarget)}
      />
    </div>
  );
}
