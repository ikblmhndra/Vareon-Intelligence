"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { Client } from "@/lib/api/loose-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { CountryMultiSelect } from "@/components/country-multi-select";
import { countryName } from "@/lib/countries";
import { useClients } from "@/components/admin/hooks";

const CLIENTS_KEY = ["admin", "clients"] as const;

/** Port section "Client Tenants" (superadmin-only, `require_superadmin`
 * di `routers/clients.py`) -- `loadUMClients()`/`umSaveClient()`/
 * `umSaveEditClient()`/`umDeleteClient()`. */
export function ClientsSection() {
  const queryClient = useQueryClient();
  const clients = useClients();
  const [addOpen, setAddOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Client | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const deleteMutation = useMutation({
    mutationFn: async (clientId: string) => {
      const { response } = await api.DELETE("/api/clients/{client_id}", {
        params: { path: { client_id: clientId } },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${response.status}`);
      }
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: CLIENTS_KEY }),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-semibold text-foreground">
          Client Tenants
        </CardTitle>
        <CardAction>
          <Button size="sm" onClick={() => setAddOpen(true)}>
            + Add Client
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {clients.isPending && <Skeleton className="h-32 w-full" />}
        {clients.isError && <p className="text-sm text-destructive">Failed to load clients.</p>}
        {clients.data && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Client ID</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Countries</TableHead>
                <TableHead>Created</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {clients.data.map((c) => (
                <TableRow key={c.client_id}>
                  <TableCell className="font-mono text-xs text-primary">{c.client_id}</TableCell>
                  <TableCell className="text-xs">{c.name}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {c.countries.length ? (
                        c.countries.map((co) => (
                          <Badge key={co} variant="outline" className="text-xs text-muted-foreground">
                            {countryName(co)}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {c.created_at.split("T")[0]}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    <Button size="sm" variant="outline" className="mr-1.5" onClick={() => setEditTarget(c)}>
                      Edit
                    </Button>
                    {c.client_id !== "default" && (
                      <Button size="sm" variant="destructive" onClick={() => setDeleteTarget(c.client_id)}>
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

      <ClientFormDialog mode="add" open={addOpen} onOpenChange={setAddOpen} />
      <ClientFormDialog
        mode="edit"
        open={editTarget !== null}
        onOpenChange={(open) => !open && setEditTarget(null)}
        client={editTarget}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Delete client"
        description={`Delete client "${deleteTarget}"? This does NOT delete their data — only the tenant record.`}
        confirmLabel="Delete"
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget)}
      />
    </Card>
  );
}

function sameCountries(a: string[], b: string[]): boolean {
  const setB = new Set(b);
  return a.length === setB.size && a.every((c) => setB.has(c));
}

/** Dialog-nya dibuka programatik (`open={editTarget !== null}`), jadi
 * `onOpenChange(true)` gak pernah kepanggil -- init state di situ bikin
 * form kebuka kosong (QA BUG-01). Body cuma mount pas `open` + `key` per
 * client: state lazy-init dari `client` tiap kali dibuka, reset pas
 * ditutup -- pola "mount-gates-freshness" sama kayak `MindmapEditorDialog`. */
function ClientFormDialog({
  mode,
  open,
  onOpenChange,
  client,
}: {
  mode: "add" | "edit";
  open: boolean;
  onOpenChange: (open: boolean) => void;
  client?: Client | null;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading">{mode === "add" ? "Add Client" : `Edit ${client?.client_id ?? ""}`}</DialogTitle>
        </DialogHeader>
        {open && (mode === "add" || client) && (
          <ClientForm
            key={client?.client_id ?? "add"}
            mode={mode}
            client={client ?? null}
            onClose={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ClientForm({
  mode,
  client,
  onClose,
}: {
  mode: "add" | "edit";
  client: Client | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [clientId, setClientId] = useState(client?.client_id ?? "");
  const [name, setName] = useState(client?.name ?? "");
  const [countries, setCountries] = useState<string[]>(client?.countries ?? []);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      if (mode === "add") {
        const { response } = await api.POST("/api/clients", {
          body: { client_id: clientId, name, countries },
        });
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(body?.detail || `HTTP ${response.status}`);
        }
      } else {
        // `countries` cuma dikirim kalau beneran berubah -- backend
        // nganggep omit = gak diubah, jadi form yang somehow kebuka tanpa
        // prefill gak bisa ngehapus country tenant diam-diam.
        const { response } = await api.PUT("/api/clients/{client_id}", {
          params: { path: { client_id: client!.client_id } },
          body: { name, ...(sameCountries(countries, client!.countries) ? {} : { countries }) },
        });
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(body?.detail || `HTTP ${response.status}`);
        }
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CLIENTS_KEY });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  function handleSave() {
    setError(null);
    if (mode === "add") {
      if (!clientId.trim() || !name.trim()) return setError("Both fields required.");
      if (!/^[a-z0-9_-]+$/.test(clientId)) return setError("Client ID: lowercase a-z, 0-9, _ or - only.");
    } else if (!name.trim()) {
      return setError("Name is required.");
    }
    mutation.mutate();
  }

  return (
    <>
      <div className="space-y-3">
        {mode === "add" && (
          <div className="space-y-1.5">
            <Label className="text-sm font-medium text-muted-foreground">
              Client ID <span className="normal-case">(lowercase, a-z 0-9 _-)</span>
            </Label>
            <Input
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              placeholder="e.g. acme_corp"
              className="font-mono text-xs"
            />
          </div>
        )}
        <div className="space-y-1.5">
          <Label className="text-sm font-medium text-muted-foreground">Display Name</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme Corp" className="text-xs" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-sm font-medium text-muted-foreground">Countries</Label>
          <CountryMultiSelect value={countries} onChange={setCountries} />
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>
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
