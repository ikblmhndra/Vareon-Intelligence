"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { AdminFrame, AdminPageHeading } from "@/components/admin/admin-frame";
import { adminErrorMessage, useApiTokens } from "@/components/admin/hooks";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useAuth } from "@/components/providers/auth-provider";
import { useCan } from "@/lib/auth/permissions";
import { fmtAgo, fmtDaysLeft, fmtShortDate } from "@/lib/format";
import { unwrap } from "@/lib/scrapers/queries";

type ApiToken = components["schemas"]["ApiTokenOut"];
type Tlp = components["schemas"]["ApiTokenCreate"]["max_tlp"];

const KEY = ["admin", "api-tokens"] as const;
const DAY_MS = 86_400_000;

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

const SCOPE_ITEMS: { value: string; help: string }[] = [
  { value: "indicators:read", help: "IOC feed and the TAXII “indicators” collection" },
  { value: "intel:read", help: "Entities, relationships, reports and the TAXII “intel” collection" },
  { value: "hunt:read", help: "Hunting packs" },
];

const STATUS_CHIP = { active: "ok", expired: "watch", revoked: "action" } as const;

/** C16: 8 karakter awal dan 4 terakhir; sisanya tidak pernah tampil di banner terkunci. */
export function maskToken(token: string): string {
  return `${token.slice(0, 8)}••••${token.slice(-4)}`;
}

type Created = { name: string; token: string };

/** Banner sekali-tampil. Token hanya ada di prop dari state halaman: tanpa cache, storage, URL, log atau toast. */
function TokenBanner({ created, onDone }: { created: Created; onDone: () => void }) {
  const [revealed, setRevealed] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function copy() {
    try {
      // `navigator.clipboard` tidak ada di HTTP biasa (instance dev): TypeError ikut ke catch.
      await navigator.clipboard.writeText(created.token);
      setNote("Copied.");
    } catch {
      // Gagal menyalin: tampilkan token supaya tidak hilang.
      setRevealed(true);
      setNote("Copy failed. Select the token and copy it manually.");
    }
  }

  return (
    <Notice tone="warning" title={`Copy the token for “${created.name}” now`} className="mb-4">
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-2">
        {revealed ? (
          <Input
            readOnly
            aria-label="API token"
            value={created.token}
            onFocus={(e) => e.currentTarget.select()}
            className="h-8 max-w-md font-code text-xs"
          />
        ) : (
          <span className="font-code text-foreground">{maskToken(created.token)}</span>
        )}
        <span>
          {" · "}it will not be shown again. Store it in the consumer&apos;s secret store.
        </span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button size="sm" variant="ghost" onClick={() => {
            setRevealed((r) => !r);
            setNote(null);
          }}>
          {revealed ? "Hide" : "Show"}
        </Button>
        <Button size="sm" variant="outline" onClick={() => void copy()}>
          Copy token
        </Button>
        <Button size="sm" onClick={onDone}>
          Done
        </Button>
        {note && <span role="status" className="text-xs text-muted-foreground">{note}</span>}
      </div>
    </Notice>
  );
}

function NewTokenDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (created: Created) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading">New API token</DialogTitle>
          <DialogDescription>The full token is shown once, right after you create it.</DialogDescription>
        </DialogHeader>
        {open && <NewTokenForm onClose={onClose} onCreated={onCreated} />}
      </DialogContent>
    </Dialog>
  );
}

function NewTokenForm({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (created: Created) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [maxTlp, setMaxTlp] = useState<Tlp>("clear");
  const [expiry, setExpiry] = useState("365");
  const [scopes, setScopes] = useState<string[]>(["indicators:read"]);
  const [scopeError, setScopeError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // Tanpa useMutation: token mentah dari respons hanya lewat variabel lokal ke `onCreated`,
  // tidak pernah di MutationCache (variables/data) atau query cache.
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setScopeError(null);
    const trimmed = name.trim();
    if (!trimmed || trimmed.length > 200) return setError("Name is required (1-200 characters).");
    if (scopes.length === 0) return setScopeError("Select at least one scope.");
    setPending(true);
    try {
      const data = unwrap(
        await api.POST("/api/api-tokens", {
          body: {
            name: trimmed,
            max_tlp: maxTlp,
            expires_in_days: expiry === "never" ? null : Number(expiry),
            scopes,
          },
        }),
        "Could not create the token",
      );
      void queryClient.invalidateQueries({ queryKey: KEY });
      onCreated({ name: trimmed, token: data.token });
      onClose();
    } catch (err) {
      setError(adminErrorMessage(err, "manage_api_tokens"));
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
      <div className="space-y-1.5">
        <Label htmlFor="api-token-name" className="text-sm font-medium text-muted-foreground">
          Name
        </Label>
        <Input
          id="api-token-name"
          maxLength={200}
          autoComplete="off"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. splunk-prod"
          className="text-sm"
        />
      </div>
      <div className="space-y-1.5">
        <Label className="text-sm font-medium text-muted-foreground">Max TLP</Label>
        <Select items={TLP_ITEMS} value={maxTlp} onValueChange={(v) => v && setMaxTlp(v as Tlp)}>
          <SelectTrigger aria-label="Max TLP" className="w-full text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(TLP_ITEMS).map(([value, label]) => (
              <SelectItem key={value} value={value} className="text-sm">
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-1.5">
        <Label className="text-sm font-medium text-muted-foreground">Expires</Label>
        <Select items={EXPIRY_ITEMS} value={expiry} onValueChange={(v) => v && setExpiry(v)}>
          <SelectTrigger aria-label="Expires" className="w-full text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(EXPIRY_ITEMS).map(([value, label]) => (
              <SelectItem key={value} value={value} className="text-sm">
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <fieldset className="space-y-1.5" aria-describedby={scopeError ? "api-token-scope-error" : undefined}>
        <legend className="text-sm font-medium text-muted-foreground">Scopes</legend>
        {SCOPE_ITEMS.map((sc) => (
          <div key={sc.value} className="flex items-start gap-2">
            <Checkbox
              id={`api-token-scope-${sc.value}`}
              aria-label={sc.value}
              checked={scopes.includes(sc.value)}
              onCheckedChange={(on) =>
                setScopes((cur) => (on ? [...cur, sc.value] : cur.filter((x) => x !== sc.value)))
              }
              className="mt-0.5"
            />
            <Label htmlFor={`api-token-scope-${sc.value}`} className="flex flex-col items-start gap-0.5">
              <span className="font-code text-xs">{sc.value}</span>
              <span className="text-2xs font-normal text-muted-foreground">{sc.help}</span>
            </Label>
          </div>
        ))}
        {scopeError && (
          <p id="api-token-scope-error" className="text-xs text-destructive-text">
            {scopeError}
          </p>
        )}
      </fieldset>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending}>
          {pending ? "Creating…" : "Create token"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function RevokeDialog({ target, onClose }: { target: ApiToken | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);

  async function confirm() {
    if (!target) return;
    setPending(true);
    try {
      unwrap(
        await api.DELETE("/api/api-tokens/{token_id}", { params: { path: { token_id: target.id } } }),
        "Could not revoke the token",
      );
      await queryClient.invalidateQueries({ queryKey: KEY });
      toast.success(`${target.name} revoked`);
      onClose();
    } catch (err) {
      toast.error(adminErrorMessage(err, "manage_api_tokens"));
    } finally {
      setPending(false);
    }
  }

  return (
    <ConfirmDialog
      open={target !== null}
      onOpenChange={(o) => !o && onClose()}
      tone="danger"
      title={`Revoke ${target?.name ?? ""}?`}
      description="Requests with this token fail from now on. This cannot be undone."
      confirmLabel="Revoke token"
      confirmLoading={pending}
      onConfirm={() => void confirm()}
    />
  );
}

/** Halaman API tokens (`/api/api-tokens`, permission `manage_api_tokens`). */
export function TokensView() {
  const can = useCan();
  const { status } = useAuth();
  const allowed = can("manage_api_tokens");
  const router = useRouter();
  const searchParams = useSearchParams();
  const tokens = useApiTokens(allowed);
  const [createOpen, setCreateOpen] = useState(false);
  const [created, setCreated] = useState<Created | null>(null);
  // Naik tiap token baru supaya Show/Copy banner mulai dari terkunci.
  const [bannerSeq, setBannerSeq] = useState(0);
  const [revokeTarget, setRevokeTarget] = useState<ApiToken | null>(null);
  const wantsNew = searchParams.get("new") === "1";

  // `?new=1` membuka dialog sekali (state disesuaikan saat render) lalu dihapus dari URL oleh effect;
  // tidak pernah menavigasi saat parameter tidak ada.
  if (wantsNew && allowed && !createOpen) setCreateOpen(true);
  // Tunggu user termuat: sebelum itu `allowed` palsu-false dan dialog terlewat.
  useEffect(() => {
    if (wantsNew && status === "authenticated") router.replace("/admin/tokens");
  }, [wantsNew, status, router]);

  let body;
  if (!allowed) {
    body = (
      <StatePanel
        variant="no-access"
        title="You need the manage_api_tokens permission"
        description="API tokens are managed by users with that permission."
      />
    );
  } else if (tokens.isPending) {
    body = (
      <div role="status">
        <Skeleton aria-hidden className="h-48 w-full" />
        <span className="sr-only">Loading API tokens</span>
      </div>
    );
  } else if (tokens.isError) {
    body = (
      <StatePanel
        variant="error"
        title="Failed to load API tokens"
        description={adminErrorMessage(tokens.error, "manage_api_tokens")}
        action={<Button variant="outline" size="sm" onClick={() => void tokens.refetch()}>Retry</Button>}
      />
    );
  } else if (tokens.data.tokens.length === 0) {
    body = <StatePanel variant="empty" title="No API token yet" />;
  } else {
    const { tokens: rows, nowMs } = tokens.data;
    body = (
      <Table framed className="table-fixed" style={{ minWidth: 1040 }}>
        <colgroup>
          <col style={{ width: "16%" }} />
          <col style={{ width: "13%" }} />
          <col style={{ width: "19%" }} />
          <col style={{ width: "10%" }} />
          <col style={{ width: "12%" }} />
          <col style={{ width: "11%" }} />
          <col style={{ width: "10%" }} />
          <col style={{ width: "6%" }} />
          <col style={{ width: "3%" }} />
        </colgroup>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Name</TableHead>
            <TableHead>Prefix</TableHead>
            <TableHead>Scopes</TableHead>
            <TableHead>Max TLP</TableHead>
            <TableHead>Created by</TableHead>
            <TableHead>Expires</TableHead>
            <TableHead>Last used</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((t) => {
            const left =
              t.status === "active" && t.expires_at
                ? Math.ceil((new Date(t.expires_at).getTime() - nowMs) / DAY_MS)
                : null;
            return (
              <TableRow key={t.id}>
                <TableCell className="truncate text-sm" title={t.name}>
                  {t.name}
                </TableCell>
                <TableCell className="truncate font-code text-xs text-muted-foreground">
                  {t.token_prefix}…
                </TableCell>
                <TableCell className="whitespace-normal font-code text-xs">{t.scopes.join(" · ")}</TableCell>
                <TableCell>
                  <Chip kind="flag" value={t.max_tlp}>
                    {TLP_ITEMS[t.max_tlp] ?? `TLP:${t.max_tlp.toUpperCase()}`}
                  </Chip>
                </TableCell>
                <TableCell className="whitespace-normal">
                  <div className="truncate font-code text-xs" title={t.created_by}>
                    {t.created_by}
                  </div>
                  <div className="text-2xs text-muted-foreground">{fmtShortDate(t.created_at)}</div>
                </TableCell>
                <TableCell className="whitespace-normal text-xs">
                  <div className="text-muted-foreground">{t.expires_at ? fmtShortDate(t.expires_at) : "never"}</div>
                  {left !== null && left <= 30 && (
                    <div className="text-2xs text-warning-text">{fmtDaysLeft(left)}</div>
                  )}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {t.last_used_at ? fmtAgo(t.last_used_at, nowMs) : "never"}
                </TableCell>
                <TableCell>
                  {t.status in STATUS_CHIP ? (
                    <Chip kind="status" value={STATUS_CHIP[t.status as keyof typeof STATUS_CHIP]}>
                      {t.status}
                    </Chip>
                  ) : (
                    <Chip kind="flag" value={t.status}>
                      {t.status}
                    </Chip>
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end">
                    <RowMenu
                      label={`Actions for ${t.name}`}
                      items={[
                        {
                          label: "Revoke",
                          destructive: true,
                          hidden: t.status !== "active",
                          onSelect: () => setRevokeTarget(t),
                        },
                      ]}
                    />
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    );
  }

  return (
    <AdminFrame page="tokens">
      <AdminPageHeading
        title="API tokens"
        description="For SIEM pulls; a token never sees above its TLP"
        action={allowed ? <Button onClick={() => setCreateOpen(true)}>+ New token</Button> : undefined}
      />
      {allowed && created && (
        <TokenBanner key={bannerSeq} created={created} onDone={() => setCreated(null)} />
      )}
      {body}
      {allowed && (
        <NewTokenDialog
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          onCreated={(c) => {
            setBannerSeq((n) => n + 1);
            setCreated(c);
          }}
        />
      )}
      {allowed && <RevokeDialog target={revokeTarget} onClose={() => setRevokeTarget(null)} />}
    </AdminFrame>
  );
}
