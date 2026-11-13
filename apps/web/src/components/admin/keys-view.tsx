"use client";

import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { AdminFrame, AdminPageHeading } from "@/components/admin/admin-frame";
import { adminErrorMessage, useSecrets } from "@/components/admin/hooks";
import { useAuth } from "@/components/providers/auth-provider";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { fmtAgo } from "@/lib/format";
import { unwrap } from "@/lib/scrapers/queries";

type Provider = components["schemas"]["SecretProviderOut"];
type Field = components["schemas"]["SecretFieldOut"];
type TestResult = components["schemas"]["SecretTestOut"];

const KEY = ["admin", "secrets"] as const;

const SOURCE_LABEL: Record<Provider["source"], string> = {
  db: "db · overrides .env",
  env: ".env",
  unset: "not set",
};

function SourceChip({ source }: { source: Provider["source"] }) {
  if (source === "env") return <Chip kind="flag" value="env">{SOURCE_LABEL.env}</Chip>;
  return (
    <Chip kind="status" value={source === "db" ? "ok" : "watch"}>
      {SOURCE_LABEL[source]}
    </Chip>
  );
}

function TestChip({ status }: { status: TestResult["status"] }) {
  if (status === "OK") return <Chip kind="status" value="ok">OK</Chip>;
  if (status === "FAIL") return <Chip kind="status" value="action">FAIL</Chip>;
  return <Chip kind="flag" value={status}>{status}</Chip>;
}

/**
 * `detail` PUT bisa objek `{message, probe}` (probe vendor gagal); `apiErrorMessage` di `unwrap`
 * akan men-JSON-kan objek itu, jadi diratakan dulu menjadi string. Isi pesan tidak pernah memuat
 * nilai secret (server hanya membalas detail probe).
 */
function unwrapKey<T>(r: { data?: T; error?: unknown; response: Response }, fallback: string): T {
  const detail = (r.error as { detail?: unknown } | null | undefined)?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const d = detail as { message?: string; probe?: { detail?: string } };
    const text = [d.message, d.probe?.detail].filter(Boolean).join(": ");
    if (text) return unwrap({ ...r, error: { detail: text } }, fallback);
  }
  return unwrap(r, fallback);
}

/** Pesan server apa adanya (mis. 403 "Password confirmation failed"); bukan terjemahan permission. */
function serverMessage(e: unknown): string {
  const m = e instanceof Error ? e.message : String(e);
  return m || "Request failed";
}

function fieldLabel(name: string): string {
  const words = name.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function keySummary(provider: Provider): string {
  const last4 = provider.fields.find((f) => f.secret && f.last4)?.last4;
  return last4 ? `••••${last4}` : "–";
}

/** Halaman Third-party keys (ROADMAP #23): superadmin saja (`require_superadmin` di `routers/secrets.py`). */
export function KeysView() {
  const { user } = useAuth();
  const allowed = user?.role === "superadmin";
  const queryClient = useQueryClient();
  const secrets = useSecrets(allowed);
  const [editTarget, setEditTarget] = useState<Provider | null>(null);
  const [revertTarget, setRevertTarget] = useState<Provider | null>(null);
  const [tests, setTests] = useState<Record<string, TestResult | "running">>({});

  // Tanpa useMutation: tidak ada variabel/respons yang perlu tinggal di MutationCache.
  async function runTest(key: string) {
    setTests((t) => ({ ...t, [key]: "running" }));
    try {
      const result = unwrapKey(
        await api.POST("/api/secrets/{provider}/test", { params: { path: { provider: key } } }),
        "Test request failed",
      );
      setTests((t) => ({ ...t, [key]: result }));
      void queryClient.invalidateQueries({ queryKey: KEY });
    } catch (e) {
      setTests((t) => ({
        ...t,
        [key]: { status: "NOTE", detail: `Test could not run: ${serverMessage(e)}` },
      }));
    }
  }

  // Hasil Test di layar menutupi `last_test_*` server; sesudah key diganti/di-revert hasil itu usang.
  function clearTest(key: string) {
    setTests((t) => {
      const next = { ...t };
      delete next[key];
      return next;
    });
  }

  const enabled = secrets.data?.enabled ?? false;
  const count = secrets.data?.providers.length;
  let body;
  if (!allowed) {
    body = (
      <StatePanel
        variant="no-access"
        title="Only a superadmin can manage third-party keys"
        description="Keys are managed by users with the superadmin role."
      />
    );
  } else if (secrets.isPending) {
    body = (
      <div role="status">
        <Skeleton aria-hidden className="h-64 w-full" />
        <span className="sr-only">Loading third-party keys</span>
      </div>
    );
  } else if (secrets.isError) {
    body = (
      <StatePanel
        variant="error"
        title="Failed to load third-party keys"
        description={adminErrorMessage(secrets.error, "superadmin")}
        action={<Button variant="outline" size="sm" onClick={() => void secrets.refetch()}>Retry</Button>}
      />
    );
  } else {
    // "Sekarang" = waktu fetch terakhir (bukan Date.now() saat render).
    const nowMs = secrets.dataUpdatedAt;
    body = (
      <ul className="divide-y divide-border rounded-lg border border-border">
        {secrets.data.providers.map((p) => {
          const test = tests[p.key];
          const blocked = !enabled || Boolean(p.error);
          const editLabel = p.source === "db" ? "Edit" : p.source === "env" ? "Override" : "Set";
          return (
            <li
              key={p.key}
              className="grid gap-3 px-4 py-3 text-sm lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1.6fr)_minmax(0,1.6fr)_auto] lg:items-center"
            >
              <div className="min-w-0 space-y-1">
                <div className="truncate font-medium text-foreground">{p.label}</div>
                <SourceChip source={p.source} />
                {p.error && (
                  <p className="text-xs text-destructive-text">
                    {p.error === "master_key_missing"
                      ? "Saved override ignored: the server has no encryption key. Using .env."
                      : "Saved override cannot be read; using .env here (running workers may keep the last good key until restarted)."}
                  </p>
                )}
              </div>
              <div className="min-w-0 text-xs">
                <span className="font-code text-foreground">{keySummary(p)}</span>
                <p className="truncate font-code text-muted-foreground">
                  {p.fields.map((f) => f.name).join(" · ")}
                </p>
              </div>
              <div className="min-w-0 text-xs" aria-live="polite">
                {test === "running" ? (
                  <span className="text-muted-foreground">Testing…</span>
                ) : test ? (
                  <div className="space-y-1">
                    <TestChip status={test.status} />
                    <p className="break-words text-muted-foreground">{test.detail}</p>
                  </div>
                ) : p.last_test_at ? (
                  <span className={p.last_test_ok ? "text-muted-foreground" : "text-destructive-text"}>
                    {p.last_test_ok ? "Test ok" : "Test failed"} · {fmtAgo(p.last_test_at, nowMs)}
                  </span>
                ) : (
                  <span className="text-muted-foreground">Not tested yet</span>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5 lg:justify-end">
                {p.source !== "unset" && (
                  <Button
                    size="sm"
                    variant="outline"
                    aria-label={`Test ${p.label}`}
                    disabled={test === "running"}
                    onClick={() => void runTest(p.key)}
                  >
                    Test
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  aria-label={`${editLabel} ${p.label}`}
                  disabled={blocked}
                  onClick={() => setEditTarget(p)}
                >
                  {editLabel}
                </Button>
                {(p.source === "db" || p.error) && (
                  <Button
                    size="sm"
                    variant="destructive"
                    aria-label={`Revert ${p.label} to .env`}
                    onClick={() => setRevertTarget(p)}
                  >
                    Revert
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <AdminFrame page="keys">
      <AdminPageHeading
        title="Third-party keys"
        description={`${count !== undefined ? `${count} providers · ` : ""}db overrides .env`}
      />
      {allowed && (
        <div className="mb-4 space-y-3">
          <Notice tone="info" title="Changing or reverting a key asks for your current password">
            Set here to override the .env value; Revert removes the override so the .env value applies again.
          </Notice>
          <p className="text-xs text-muted-foreground">
            Keys saved here are encrypted in the database and take effect within about 30 seconds, without a
            restart. A saved key is never shown again (only its last four characters). Keep the .env value
            equal to the active key or blank, and never leave a revoked key there.
          </p>
          {secrets.data && !secrets.data.enabled && (
            <Notice tone="destructive" title="The server has no encryption key">
              Keys cannot be changed here (<span className="font-code">SECRETS_ENCRYPTION_KEYS</span> is not set).
              Showing the <span className="font-code">.env</span> status only.
            </Notice>
          )}
        </div>
      )}
      {body}
      <KeyEditDialog
        provider={editTarget}
        onOpenChange={() => setEditTarget(null)}
        onSaved={clearTest}
      />
      <KeyRevertDialog
        provider={revertTarget}
        onOpenChange={() => setRevertTarget(null)}
        onSaved={clearTest}
      />
    </AdminFrame>
  );
}

type DialogProps = {
  provider: Provider | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (key: string) => void;
};

export function KeyEditDialog({ provider, onOpenChange, onSaved }: DialogProps) {
  const [busy, setBusy] = useState(false);
  const verb = provider?.source === "db" ? "Edit" : provider?.source === "env" ? "Override" : "Set";
  return (
    <Dialog open={provider !== null} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading">
            {provider ? (verb === "Set" ? `Set ${provider.label}` : `${verb} ${provider.label}`) : ""}
          </DialogTitle>
          <DialogDescription>The new value is tested with the provider before it is saved.</DialogDescription>
        </DialogHeader>
        {/* Dipasang hanya saat terbuka: secret dan password yang diketik hilang saat ditutup. */}
        {provider && <KeyEditForm provider={provider} onBusy={setBusy} onClose={() => onOpenChange(false)} onSaved={onSaved} />}
      </DialogContent>
    </Dialog>
  );
}

function KeyEditForm({
  provider,
  onBusy,
  onClose,
  onSaved,
}: {
  provider: Provider;
  onBusy: (busy: boolean) => void;
  onClose: () => void;
  onSaved: (key: string) => void;
}) {
  const queryClient = useQueryClient();
  const isLlm = provider.key === "llm";
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(provider.fields.map((f) => [f.name, f.secret ? "" : (f.value ?? "")])),
  );
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  function buildFields(): Record<string, string | null> {
    const fields: Record<string, string | null> = {};
    for (const f of provider.fields) {
      const v = (values[f.name] ?? "").trim();
      if (f.secret) {
        if (v) fields[f.name] = v;
      } else if (isLlm) {
        // Paket llm: server menolak override yang tidak membawa provider, model, dan url sekaligus.
        fields[f.name] = v;
      } else if (v !== (f.value ?? "")) {
        fields[f.name] = v;
      }
    }
    return fields;
  }

  const typedSecret = provider.fields.some((f) => f.secret && (values[f.name] ?? "").trim());
  const changedPlain = provider.fields.some(
    (f) => !f.secret && (values[f.name] ?? "").trim() !== (f.value ?? ""),
  );
  const canSave = (typedSecret || changedPlain) && password.length > 0;

  // Plain async submit: secret dan password hanya di closure/state, tidak di MutationCache.
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    onBusy(true);
    try {
      const data = unwrapKey(
        await api.PUT("/api/secrets/{provider}", {
          params: { path: { provider: provider.key } },
          body: { fields: buildFields(), current_password: password },
        }),
        "Could not save the key",
      );
      onSaved(provider.key);
      await queryClient.invalidateQueries({ queryKey: KEY });
      if (data.probe && data.probe.status !== "OK") {
        toast.warning(`Saved, but the key was not verified (${data.probe.status}): ${data.probe.detail}`);
      } else {
        toast.success(`${provider.label} saved`);
      }
      onBusy(false);
      onClose();
    } catch (err) {
      setError(serverMessage(err));
      setPending(false);
      onBusy(false);
    }
  }

  function renderField(f: Field) {
    const id = `key-${provider.key}-${f.name}`;
    const set = (v: string) => setValues((cur) => ({ ...cur, [f.name]: v }));
    return (
      <div key={f.name} className="space-y-1.5">
        <Label htmlFor={id} className="text-sm font-medium text-muted-foreground">
          {fieldLabel(f.name)}
          {f.secret && f.last4 && <span className="ml-1 font-code normal-case">(current …{f.last4})</span>}
        </Label>
        {f.secret ? (
          <Input
            id={id}
            type="password"
            autoComplete="off"
            data-1p-ignore
            data-lpignore="true"
            spellCheck={false}
            placeholder="Leave blank to keep the current key"
            value={values[f.name] ?? ""}
            onChange={(e) => set(e.target.value)}
            className="font-code text-sm"
          />
        ) : f.choices.length > 0 ? (
          <Select
            items={Object.fromEntries(f.choices.map((c) => [c, c]))}
            value={values[f.name] ?? ""}
            onValueChange={(v) => v !== null && set(v)}
          >
            <SelectTrigger id={id} className="w-full font-code text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {f.choices.map((c) => (
                <SelectItem key={c} value={c} className="font-code text-sm">
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input
            id={id}
            autoComplete="off"
            spellCheck={false}
            value={values[f.name] ?? ""}
            onChange={(e) => set(e.target.value)}
            className="font-code text-sm"
          />
        )}
        {isLlm && f.name === "url" && (
          <p className="text-2xs text-muted-foreground">
            Leave empty for the vendor default. Outside dev the server only accepts allow-listed https hosts.
          </p>
        )}
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="grid gap-4">
      {error && (
        <div role="alert">
          <Notice tone="destructive" title={error} />
        </div>
      )}
      {provider.fields.map(renderField)}
      <div className="space-y-1.5">
        <Label htmlFor={`key-${provider.key}-password`} className="text-sm font-medium text-muted-foreground">
          Your current password
        </Label>
        <Input
          id={`key-${provider.key}-password`}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="text-sm"
        />
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" disabled={pending} onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending || !canSave}>
          {pending ? "Testing and saving…" : "Save and test"}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function KeyRevertDialog({ provider, onOpenChange, onSaved }: DialogProps) {
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={provider !== null} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="font-heading">{provider ? `Revert ${provider.label} to .env?` : ""}</DialogTitle>
          <DialogDescription>The saved override is deleted and the .env value applies again.</DialogDescription>
        </DialogHeader>
        {provider && <KeyRevertForm provider={provider} onBusy={setBusy} onClose={() => onOpenChange(false)} onSaved={onSaved} />}
      </DialogContent>
    </Dialog>
  );
}

function KeyRevertForm({
  provider,
  onBusy,
  onClose,
  onSaved,
}: {
  provider: Provider;
  onBusy: (busy: boolean) => void;
  onClose: () => void;
  onSaved: (key: string) => void;
}) {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    onBusy(true);
    try {
      unwrapKey(
        await api.DELETE("/api/secrets/{provider}", {
          params: { path: { provider: provider.key } },
          body: { current_password: password },
        }),
        "Could not revert the key",
      );
      onSaved(provider.key);
      await queryClient.invalidateQueries({ queryKey: KEY });
      toast.success(`${provider.label} reverted to .env`);
      onBusy(false);
      onClose();
    } catch (err) {
      setError(serverMessage(err));
      setPending(false);
      onBusy(false);
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
        <Label htmlFor={`revert-${provider.key}-password`} className="text-sm font-medium text-muted-foreground">
          Your current password
        </Label>
        <Input
          id={`revert-${provider.key}-password`}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="text-sm"
        />
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" disabled={pending} onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" variant="destructive" disabled={pending || !password}>
          {pending ? "Reverting…" : "Revert"}
        </Button>
      </DialogFooter>
    </form>
  );
}
