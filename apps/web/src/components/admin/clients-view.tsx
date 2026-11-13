"use client";

import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { AdminFrame, AdminPageHeading } from "@/components/admin/admin-frame";
import { adminErrorMessage, useAdminUsers, useClients } from "@/components/admin/hooks";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { CountryMultiSelect } from "@/components/country-multi-select";
import { Button } from "@/components/ui/button";
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
import { api } from "@/lib/api/client";
import type { Client } from "@/lib/api/loose-types";
import { useCan } from "@/lib/auth/permissions";
import { countryName } from "@/lib/countries";
import { fmtShortDate } from "@/lib/format";
import { unwrap } from "@/lib/scrapers/queries";

const CLIENTS_KEY = ["admin", "clients"] as const;
const ID_RE = /^[a-z0-9_-]{1,64}$/;

function sameCountries(a: string[], b: string[]): boolean {
  const setB = new Set(b);
  return a.length === setB.size && a.every((c) => setB.has(c));
}

type DialogState = { mode: "add" } | { mode: "edit"; client: Client } | null;

/** Dialog Add / Edit client. Body hanya mount saat `open` supaya state lazy-init dari `client` tiap dibuka (QA BUG-01 lama). */
function ClientDialog({ state, onClose }: { state: DialogState; onClose: () => void }) {
  const edit = state?.mode === "edit" ? state.client : null;
  return (
    <Dialog open={state !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading">{edit ? `Edit ${edit.client_id}` : "Add client"}</DialogTitle>
          <DialogDescription>Countries decide which regional content this tenant sees.</DialogDescription>
        </DialogHeader>
        {state && <ClientForm key={edit?.client_id ?? "add"} client={edit} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function ClientForm({ client, onClose }: { client: Client | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [clientId, setClientId] = useState(client?.client_id ?? "");
  const [name, setName] = useState(client?.name ?? "");
  const [countries, setCountries] = useState<string[]>(client?.countries ?? []);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const idOk = client !== null || ID_RE.test(clientId);
  const nameOk = name.trim().length >= 1 && name.trim().length <= 128;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      if (client) {
        // `countries` hanya dikirim bila berubah: omit = tidak diubah di backend, jadi form tanpa prefill tak menghapus diam-diam.
        unwrap(
          await api.PUT("/api/clients/{client_id}", {
            params: { path: { client_id: client.client_id } },
            body: { name: name.trim(), ...(sameCountries(countries, client.countries) ? {} : { countries }) },
          }),
          "Could not save the client",
        );
      } else {
        unwrap(
          await api.POST("/api/clients", { body: { client_id: clientId, name: name.trim(), countries } }),
          "Could not add the client",
        );
      }
      await queryClient.invalidateQueries({ queryKey: CLIENTS_KEY });
      toast.success(client ? `Client ${client.client_id} saved` : `Client ${clientId} added`);
      onClose();
    } catch (err) {
      setError(adminErrorMessage(err, "manage_clients"));
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid gap-4">
      {error && (
        <div role="alert">
          <Notice tone="destructive" title={error} />
        </div>
      )}
      {!client && (
        <div className="space-y-1.5">
          <Label htmlFor="client-id" className="text-sm font-medium text-muted-foreground">
            Client ID
          </Label>
          <Input
            id="client-id"
            autoComplete="off"
            value={clientId}
            placeholder="e.g. acme_corp"
            aria-invalid={clientId !== "" && !idOk}
            aria-describedby="client-id-help"
            onChange={(e) => setClientId(e.target.value)}
            className="font-code text-sm"
          />
          <p
            id="client-id-help"
            className={`text-xs ${clientId !== "" && !idOk ? "text-destructive-text" : "text-muted-foreground"}`}
          >
            1-64 characters: a-z, 0-9, _ or -
          </p>
        </div>
      )}
      <div className="space-y-1.5">
        <Label htmlFor="client-name" className="text-sm font-medium text-muted-foreground">
          Display name
        </Label>
        <Input
          id="client-name"
          maxLength={128}
          value={name}
          placeholder="Acme Corp"
          onChange={(e) => setName(e.target.value)}
          className="text-sm"
        />
      </div>
      <div className="space-y-1.5">
        <Label className="text-sm font-medium text-muted-foreground">Countries</Label>
        <CountryMultiSelect value={countries} onChange={setCountries} />
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending || !idOk || !nameOk}>
          {pending ? "Saving…" : client ? "Save client" : "Add client"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function DeleteClientDialog({ target, onClose }: { target: Client | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const id = target?.client_id ?? "";

  async function confirm() {
    setPending(true);
    try {
      unwrap(
        await api.DELETE("/api/clients/{client_id}", { params: { path: { client_id: id } } }),
        "Could not delete the client",
      );
      await queryClient.invalidateQueries({ queryKey: CLIENTS_KEY });
      toast.success(`Client ${id} deleted`);
      onClose();
    } catch (err) {
      // Klien yang masih dipakai user bisa gagal di FK sebagai 500 polos; "Internal Server Error" mentah tak berguna.
      toast.error(
        err instanceof Error && typeof err.cause === "number" && err.cause >= 500
          ? "Could not delete the client. It may still be assigned to users."
          : adminErrorMessage(err, "manage_clients"),
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
      title={`Delete client ${id}?`}
      description="Its users lose access to this tenant. This cannot be undone."
      confirmLabel="Delete client"
      confirmLoading={pending}
      onConfirm={() => void confirm()}
    />
  );
}

/** Halaman Clients. GET /clients butuh `manage_users`; tulis (POST/PUT/DELETE) butuh `manage_clients`. */
export function ClientsView() {
  const can = useCan();
  const canList = can("manage_users");
  const canWrite = can("manage_clients");
  const clients = useClients(canList);
  const users = useAdminUsers(canList);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [deleteTarget, setDeleteTarget] = useState<Client | null>(null);

  let body;
  if (!canList) {
    body = (
      <StatePanel
        variant="no-access"
        title="You need the manage_users permission to list clients"
        description="You can still add a client; the list itself is only shown to user managers."
      />
    );
  } else if (clients.isPending) {
    body = (
      <div role="status">
        <Skeleton aria-hidden className="h-48 w-full" />
        <span className="sr-only">Loading clients</span>
      </div>
    );
  } else if (clients.isError) {
    body = (
      <StatePanel
        variant="error"
        title="Failed to load clients"
        description={adminErrorMessage(clients.error, "manage_users")}
        action={<Button variant="outline" size="sm" onClick={() => void clients.refetch()}>Retry</Button>}
      />
    );
  } else if (clients.data.length === 0) {
    body = <StatePanel variant="empty" title="No client yet" />;
  } else {
    body = (
      <Table framed className="table-fixed" style={{ minWidth: 880 }}>
        <colgroup>
          <col style={{ width: "20%" }} />
          <col style={{ width: "22%" }} />
          <col style={{ width: "28%" }} />
          <col style={{ width: "8%" }} />
          <col style={{ width: "12%" }} />
          <col style={{ width: "10%" }} />
        </colgroup>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Client ID</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>Countries</TableHead>
            <TableHead>Users</TableHead>
            <TableHead>Created</TableHead>
            <TableHead>
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {clients.data.map((c) => (
            <TableRow key={c.client_id}>
              <TableCell className="truncate font-code text-xs text-foreground" title={c.client_id}>
                {c.client_id}
              </TableCell>
              <TableCell className="truncate text-sm" title={c.name}>
                {c.name}
              </TableCell>
              <TableCell className="whitespace-normal">
                {c.countries.length ? (
                  <div className="flex flex-wrap gap-1">
                    {c.countries.map((co) => (
                      <Chip key={co} kind="flag" value={co}>
                        {countryName(co)}
                      </Chip>
                    ))}
                  </div>
                ) : (
                  <span className="text-muted-foreground">–</span>
                )}
              </TableCell>
              <TableCell className="text-sm tabular-nums">
                {users.data ? (
                  users.data.users.filter((u) => u.client_ids.includes(c.client_id)).length
                ) : users.isError ? (
                  <span className="text-muted-foreground">–</span>
                ) : (
                  <Skeleton aria-hidden className="h-4 w-6" />
                )}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">{fmtShortDate(c.created_at)}</TableCell>
              <TableCell>
                {canWrite && (
                  <div className="flex items-center justify-end gap-1">
                    <Button size="sm" variant="outline" onClick={() => setDialog({ mode: "edit", client: c })}>
                      Edit
                    </Button>
                    {c.client_id !== "default" && (
                      <RowMenu
                        label={`Actions for ${c.client_id}`}
                        items={[{ label: "Delete", destructive: true, onSelect: () => setDeleteTarget(c) }]}
                      />
                    )}
                  </div>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );
  }

  return (
    <AdminFrame page="clients">
      <AdminPageHeading
        title="Clients"
        description="Tenants and the countries each one watches."
        action={canWrite ? <Button onClick={() => setDialog({ mode: "add" })}>+ Add client</Button> : undefined}
      />
      {body}
      {canWrite && <ClientDialog state={dialog} onClose={() => setDialog(null)} />}
      {canWrite && <DeleteClientDialog target={deleteTarget} onClose={() => setDeleteTarget(null)} />}
    </AdminFrame>
  );
}
