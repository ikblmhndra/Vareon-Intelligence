"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ConfirmDialog } from "@/components/confirm-dialog";

type ApiToken = components["schemas"]["ApiTokenOut"];
type Tlp = components["schemas"]["ApiTokenCreate"]["max_tlp"];

const KEY = ["admin", "api-tokens"] as const;

const TLP_ITEMS: Record<string, string> = {
  clear: "TLP:CLEAR",
  green: "TLP:GREEN",
  amber: "TLP:AMBER",
  "amber+strict": "TLP:AMBER+STRICT",
  red: "TLP:RED",
};

// Nilai = `expires_in_days` ke API (null = tidak pernah kedaluwarsa).
const EXPIRY_ITEMS: Record<string, string> = {
  "365": "365 days",
  "90": "90 days",
  never: "Never",
};

const STATUS_CLASS: Record<string, string> = {
  active: "bg-success/10 text-success-text",
  expired: "bg-warning/10 text-warning-text",
  revoked: "bg-destructive/10 text-destructive",
};

async function failIfNotOk(response: Response) {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `HTTP ${response.status}`);
  }
}

function daysLeft(t: ApiToken): number | null {
  if (t.status !== "active" || !t.expires_at) return null;
  return Math.ceil((new Date(t.expires_at).getTime() - Date.now()) / 86_400_000);
}

/** Kelola token API mesin (`/api/api-tokens`, permission `manage_api_tokens`).
 * Token mentah hanya ada di state dialog hasil -- tidak masuk query cache. */
export function ApiTokensSection() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [created, setCreated] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<ApiToken | null>(null);

  const tokens = useQuery({
    queryKey: KEY,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/api-tokens");
      if (!response.ok || !data) throw new Error(`HTTP ${response.status}`);
      return data;
    },
  });

  const revoke = useMutation({
    mutationFn: async (id: number) => {
      const { response } = await api.DELETE("/api/api-tokens/{token_id}", {
        params: { path: { token_id: id } },
      });
      await failIfNotOk(response);
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: KEY }),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-semibold text-foreground">API tokens</CardTitle>
        <CardAction>
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            Create token
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {tokens.isPending && <Skeleton className="h-32 w-full" />}
        {tokens.isError && <p className="text-sm text-destructive">Failed to load API tokens.</p>}
        {revoke.isError && <p className="mb-2 text-xs text-destructive">{revoke.error.message}</p>}
        {tokens.data && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Token</TableHead>
                <TableHead>Max TLP</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Expires</TableHead>
                <TableHead>Last used</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {tokens.data.map((t) => {
                const left = daysLeft(t);
                return (
                  <TableRow key={t.id}>
                    <TableCell className="text-xs">{t.name}</TableCell>
                    <TableCell className="font-code text-xs text-muted-foreground">{t.token_prefix}…</TableCell>
                    <TableCell className="font-code text-xs">
                      {TLP_ITEMS[t.max_tlp] ?? t.max_tlp}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        <Badge variant="outline" className={STATUS_CLASS[t.status]}>
                          {t.status}
                        </Badge>
                        {left !== null && left < 14 && (
                          <Badge variant="outline" className="text-xs text-warning-text">
                            {`expires in ${Math.max(left, 0)} d`}
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="font-code text-xs text-muted-foreground">
                      {t.created_at.split("T")[0]}
                    </TableCell>
                    <TableCell className="font-code text-xs text-muted-foreground">
                      {t.expires_at ? t.expires_at.split("T")[0] : "never"}
                    </TableCell>
                    <TableCell className="font-code text-xs text-muted-foreground">
                      {t.last_used_at ? t.last_used_at.replace("T", " ").slice(0, 16) : "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {t.status !== "revoked" && (
                        <Button size="sm" variant="destructive" onClick={() => setRevokeTarget(t)}>
                          Revoke
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="font-heading">Create token</DialogTitle>
          </DialogHeader>
          {createOpen && (
            <CreateForm
              onClose={() => setCreateOpen(false)}
              onCreated={(token) => {
                setCreateOpen(false);
                setCreated(token);
                void queryClient.invalidateQueries({ queryKey: KEY });
              }}
            />
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={created !== null} onOpenChange={(open) => !open && setCreated(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="font-heading">Token created</DialogTitle>
          </DialogHeader>
          {created !== null && <TokenResult token={created} onClose={() => setCreated(null)} />}
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={revokeTarget !== null}
        onOpenChange={(open) => !open && setRevokeTarget(null)}
        title="Revoke token"
        description={`Revoke token "${revokeTarget?.name}"? Clients using it stop working at once.`}
        confirmLabel="Revoke"
        onConfirm={() => revokeTarget && revoke.mutate(revokeTarget.id)}
      />
    </Card>
  );
}

function CreateForm({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (token: string) => void;
}) {
  const [name, setName] = useState("");
  const [maxTlp, setMaxTlp] = useState<Tlp>("amber");
  const [expiry, setExpiry] = useState("365");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      const { data, response } = await api.POST("/api/api-tokens", {
        body: {
          name: name.trim(),
          max_tlp: maxTlp,
          expires_in_days: expiry === "never" ? null : Number(expiry),
        },
      });
      await failIfNotOk(response);
      if (!data) throw new Error("Empty response");
      return data.token;
    },
    onSuccess: onCreated,
    onError: (e: Error) => setError(e.message),
  });

  function handleSave() {
    setError(null);
    if (!name.trim()) return setError("Name is required.");
    mutation.mutate();
  }

  return (
    <>
      <div className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="api-token-name" className="text-sm font-medium text-muted-foreground">
            Name
          </Label>
          <Input
            id="api-token-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. splunk-prod"
            className="text-xs"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-sm font-medium text-muted-foreground">Max TLP</Label>
          <Select items={TLP_ITEMS} value={maxTlp} onValueChange={(v) => v && setMaxTlp(v as Tlp)}>
            <SelectTrigger aria-label="Max TLP" className="w-full text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(TLP_ITEMS).map(([value, label]) => (
                <SelectItem key={value} value={value} className="text-xs">
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label className="text-sm font-medium text-muted-foreground">Expires</Label>
          <Select items={EXPIRY_ITEMS} value={expiry} onValueChange={(v) => v && setExpiry(v)}>
            <SelectTrigger aria-label="Expires" className="w-full text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(EXPIRY_ITEMS).map(([value, label]) => (
                <SelectItem key={value} value={value} className="text-xs">
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={handleSave} disabled={mutation.isPending}>
          Create token
        </Button>
      </DialogFooter>
    </>
  );
}

function TokenResult({ token, onClose }: { token: string; onClose: () => void }) {
  const [note, setNote] = useState<string | null>(null);

  async function copy() {
    try {
      await navigator.clipboard.writeText(token);
      setNote("Copied.");
    } catch {
      setNote("Copy failed. Select the token and copy it manually.");
    }
  }

  return (
    <>
      <p className="text-sm text-muted-foreground">Copy it now. You will not see this token again.</p>
      <Input
        readOnly
        aria-label="API token"
        value={token}
        onFocus={(e) => e.currentTarget.select()}
        className="font-code text-xs"
      />
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Close
        </Button>
        <Button onClick={() => void copy()}>Copy</Button>
      </DialogFooter>
    </>
  );
}
