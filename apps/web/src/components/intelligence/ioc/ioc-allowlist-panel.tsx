"use client";

import { useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { invalidateIocViews } from "@/components/intelligence/ioc/ioc-detail-body";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatePanel } from "@/components/ui/state-panel";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { IocAllowlistEntry, IocAllowlistResponse } from "@/lib/api/loose-types";
import { useCan } from "@/lib/auth/permissions";
import { fmtShortDate } from "@/lib/format";

const TYPE_LABEL: Record<string, string> = { ip: "IP address", url_domain: "URL domain", email_domain: "Email domain" };
const TYPES = Object.keys(TYPE_LABEL) as ("ip" | "url_domain" | "email_domain")[];
const NOTE_MAX = 300;

/** Daftar allowlist; dipakai juga hitungan pil "Allowlist" (kunci query sama = satu fetch). */
export function useIocAllowlist() {
  return useQuery({
    queryKey: ["intelligence", "ioc-allowlist"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/iocs/allowlist");
      if (error) throw error;
      return data as unknown as IocAllowlistResponse;
    },
  });
}

/** Tampilan "Allowlist" (spec 2b 6.9): domain/email/IP yang dikecualikan dari deteksi IOC. Form sebaris
 * Type/Value/Note (Note maks 300, kosong = null di server) hanya untuk `manage_ioc`; hapus lewat konfirmasi. */
export function IocAllowlistPanel() {
  const can = useCan();
  const manage = can("manage_ioc");
  const qc = useQueryClient();
  const uid = useId();
  const [type, setType] = useState<(typeof TYPES)[number]>("url_domain");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [adding, setAdding] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<IocAllowlistEntry | null>(null);
  const [removing, setRemoving] = useState(false);
  const query = useIocAllowlist();

  async function add() {
    const v = value.trim();
    if (!v) return;
    setAdding(true);
    try {
      const { error } = await api.POST("/api/iocs/allowlist", { body: { type, value: v, note: note.trim() || null } });
      if (error) throw new Error(JSON.stringify(error));
      toast.success("Added to allowlist.");
      setValue("");
      setNote("");
      invalidateIocViews(qc);
    } catch (e) {
      toast.error(`Could not add: ${(e as Error).message}`);
    } finally {
      setAdding(false);
    }
  }

  async function remove(entry: IocAllowlistEntry) {
    setRemoving(true);
    try {
      const { error } = await api.DELETE("/api/iocs/allowlist/{entry_id}", { params: { path: { entry_id: entry.id } } });
      if (error) throw new Error(JSON.stringify(error));
      toast.success("Removed from allowlist.");
      invalidateIocViews(qc);
    } catch (e) {
      toast.error(`Remove failed: ${(e as Error).message}`);
    } finally {
      setRemoving(false);
      setRemoveTarget(null);
    }
  }

  const entries = query.data?.entries ?? [];

  return (
    <Card>
      <div className="flex flex-col gap-4 px-5">
        <div>
          <h2 className="font-heading text-base font-semibold">Allowlist</h2>
          <p className="text-xs text-muted-foreground">Values here are never extracted as indicators.</p>
        </div>
        {manage && (
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void add();
            }}
          >
            <div className="flex flex-col gap-1">
              <label htmlFor={`${uid}-type`} className="text-2xs font-semibold text-muted-foreground uppercase">
                Type
              </label>
              <Select items={TYPE_LABEL} value={type} onValueChange={(v) => v && setType(v as (typeof TYPES)[number])}>
                <SelectTrigger id={`${uid}-type`} size="sm" className="w-36 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {TYPE_LABEL[t]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor={`${uid}-value`} className="text-2xs font-semibold text-muted-foreground uppercase">
                Value
              </label>
              <Input
                id={`${uid}-value`}
                placeholder="e.g. example.com"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                className="h-8 w-56 font-code text-xs"
              />
            </div>
            <div className="flex min-w-48 flex-1 flex-col gap-1">
              <label htmlFor={`${uid}-note`} className="text-2xs font-semibold text-muted-foreground uppercase">
                Note
              </label>
              <Input
                id={`${uid}-note`}
                placeholder="Optional"
                maxLength={NOTE_MAX}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="h-8 text-xs"
              />
            </div>
            <Button type="submit" size="sm" loading={adding} disabled={!value.trim()}>
              Add to allowlist
            </Button>
          </form>
        )}
      </div>

      <div className="px-2">
        {query.isPending && <StatePanel variant="loading" title="Loading allowlist" className="mx-3" />}
        {query.isError && (
          <StatePanel
            variant="error"
            title="Could not load the allowlist"
            className="mx-3"
            action={
              <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
                Retry
              </Button>
            }
          />
        )}
        {query.data && entries.length === 0 && (
          <StatePanel variant="empty" title="The allowlist is empty" className="mx-3" />
        )}
        {entries.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-3">Type</TableHead>
                <TableHead>Value</TableHead>
                <TableHead>Note</TableHead>
                <TableHead>Added</TableHead>
                <TableHead>
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="pl-3">
                    <Chip kind="flag" value={TYPE_LABEL[e.type] ?? e.type} />
                  </TableCell>
                  <TableCell className="max-w-64 truncate font-code text-xs text-foreground" title={e.value}>
                    {e.value}
                  </TableCell>
                  <TableCell className="max-w-64 text-xs whitespace-normal text-muted-foreground">{e.note || "—"}</TableCell>
                  <TableCell className="text-xs whitespace-nowrap text-muted-foreground">
                    {e.added_by || "—"} · {fmtShortDate(e.added_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    {manage && (
                      <Button variant="link" size="sm" onClick={() => setRemoveTarget(e)} aria-label={`Remove ${e.value} from allowlist`}>
                        Remove
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title={`Remove ${removeTarget?.value ?? ""} from the allowlist?`}
        description="New articles can extract it as an indicator again."
        confirmLabel="Remove"
        cancelVariant="ghost"
        tone="danger"
        confirmLoading={removing}
        onConfirm={() => removeTarget && void remove(removeTarget)}
      />
    </Card>
  );
}
