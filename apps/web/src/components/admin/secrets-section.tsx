"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

type Provider = components["schemas"]["SecretProviderOut"];
type Field = components["schemas"]["SecretFieldOut"];
type TestResult = components["schemas"]["SecretTestOut"];

const SECRETS_KEY = ["admin", "secrets"] as const;

/** `detail` backend bisa string, daftar galat validasi, atau objek `{message, probe}` (probe gagal). */
function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((e) => (e as { msg?: string }).msg).filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  if (detail && typeof detail === "object") {
    const d = detail as { message?: string; probe?: { detail?: string } };
    const text = [d.message, d.probe?.detail].filter(Boolean).join(": ");
    if (text) return text;
  }
  return `HTTP ${status}`;
}

function fieldLabel(name: string): string {
  const words = name.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function formatWhen(iso: string | null): string {
  return iso ? `${iso.slice(0, 16).replace("T", " ")} UTC` : "";
}

const SOURCE_LABEL: Record<Provider["source"], string> = {
  db: "Admin override",
  env: ".env",
  unset: "Not set",
};

/**
 * Kelola key third-party (ROADMAP #23), superadmin-only (`require_superadmin` di
 * `routers/secrets.py`; cek peran di sini cuma UI). Nilai secret TIDAK PERNAH dikirim balik dari
 * server: kartu hanya menampilkan empat karakter terakhir. Setiap ubah/revert meminta password akun
 * yang sedang login (server menolak tanpa itu). Key baru diprobe ke vendor SEBELUM disimpan, jadi
 * salah ketik muncul sebagai galat di dialog, bukan sebagai pipeline yang macet.
 */
export function SecretsSection() {
  const queryClient = useQueryClient();
  const secrets = useQuery({
    queryKey: SECRETS_KEY,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/secrets");
      if (!response.ok || !data) throw new Error(`HTTP ${response.status}`);
      return data;
    },
  });
  const [editTarget, setEditTarget] = useState<Provider | null>(null);
  const [revertTarget, setRevertTarget] = useState<Provider | null>(null);
  const [tests, setTests] = useState<Record<string, TestResult | "running">>({});

  const testMutation = useMutation({
    mutationFn: async (provider: string) => {
      // `error` (bukan `response.json()`): openapi-fetch sudah menghabiskan body respons galat.
      const { data, error, response } = await api.POST("/api/secrets/{provider}/test", {
        params: { path: { provider } },
      });
      if (!response.ok || !data) throw new Error(errorMessage(error, response.status));
      return data;
    },
    onMutate: (provider) => setTests((t) => ({ ...t, [provider]: "running" })),
    onSuccess: (result, provider) => {
      setTests((t) => ({ ...t, [provider]: result }));
      void queryClient.invalidateQueries({ queryKey: SECRETS_KEY });
    },
    onError: (e: Error, provider) =>
      setTests((t) => ({
        ...t,
        [provider]: { status: "NOTE", detail: `Test could not run: ${e.message}` },
      })),
  });

  const enabled = secrets.data?.enabled ?? false;

  // Hasil Test yang tampil menutupi `last_test_*` dari server; setelah key diganti atau di-revert
  // hasil lama itu bukan milik nilai yang sekarang, jadi dibuang.
  function clearTest(key: string) {
    setTests((t) => {
      const next = { ...t };
      delete next[key];
      return next;
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-semibold text-foreground">Third-party Keys</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground">
          Keys saved here are encrypted in the database and take effect within about 30 seconds,
          without a restart. A saved key is never shown again (only its last four characters). The
          value in <span className="font-mono">.env</span> stays as a fallback, so keep it equal to
          the active key or blank, and never leave a revoked key there.
        </p>
        {secrets.data && !secrets.data.enabled && (
          <p className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive-text">
            The server has no encryption key (<span className="font-mono">SECRETS_ENCRYPTION_KEYS</span>
            ), so keys cannot be changed here. Showing the <span className="font-mono">.env</span>{" "}
            status only.
          </p>
        )}
        {secrets.isPending && <Skeleton className="h-40 w-full" />}
        {secrets.isError && <p className="text-sm text-destructive">Failed to load keys.</p>}
        {secrets.data && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Provider</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Key</TableHead>
                <TableHead>Last test</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {secrets.data.providers.map((p) => (
                <ProviderRow
                  key={p.key}
                  provider={p}
                  enabled={enabled}
                  test={tests[p.key]}
                  onTest={() => testMutation.mutate(p.key)}
                  onEdit={() => setEditTarget(p)}
                  onRevert={() => setRevertTarget(p)}
                />
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      {editTarget && (
        <SecretEditDialog
          key={editTarget.key}
          provider={editTarget}
          onSaved={() => clearTest(editTarget.key)}
          onClose={() => setEditTarget(null)}
        />
      )}
      {revertTarget && (
        <SecretRevertDialog
          key={revertTarget.key}
          provider={revertTarget}
          onSaved={() => clearTest(revertTarget.key)}
          onClose={() => setRevertTarget(null)}
        />
      )}
    </Card>
  );
}

function keySummary(provider: Provider): string {
  const secretFields = provider.fields.filter((f) => f.secret);
  const parts = secretFields.map((f) => {
    if (f.source === "unset") return "not set";
    const tail = f.last4 ? `…${f.last4}` : "set";
    // Override admin tanpa key (mis. hanya model llm diubah): key yang dipakai tetap dari .env.
    return provider.source === "db" && f.source === "env" ? `${tail} (.env)` : tail;
  });
  return parts.join(", ") || "—";
}

function configSummary(provider: Provider): string {
  return provider.fields
    .filter((f) => !f.secret && f.value)
    .map((f) => f.value)
    .join(" · ");
}

function ProviderRow({
  provider,
  enabled,
  test,
  onTest,
  onEdit,
  onRevert,
}: {
  provider: Provider;
  enabled: boolean;
  test: TestResult | "running" | undefined;
  onTest: () => void;
  onEdit: () => void;
  onRevert: () => void;
}) {
  const config = configSummary(provider);
  return (
    <TableRow>
      <TableCell className="text-xs font-medium">{provider.label}</TableCell>
      <TableCell className="space-y-1">
        <Badge
          variant={provider.source === "db" ? "default" : "outline"}
          className="text-xs"
        >
          {SOURCE_LABEL[provider.source]}
        </Badge>
        {provider.error && (
          <p className="text-xs text-destructive">
            {provider.error === "master_key_missing"
              ? "Saved override ignored: the server has no encryption key. Using .env."
              : "Saved override cannot be read; using .env here (running workers may keep the last good key until restarted)."}
          </p>
        )}
      </TableCell>
      <TableCell className="text-xs">
        <span className="font-mono">{keySummary(provider)}</span>
        {config && <p className="text-muted-foreground">{config}</p>}
      </TableCell>
      <TableCell className="text-xs whitespace-normal">
        {test === "running" && <span className="text-muted-foreground">Testing…</span>}
        {test && test !== "running" && (
          <div>
            <Badge
              variant={test.status === "FAIL" ? "destructive" : "outline"}
              className="text-xs"
            >
              {test.status}
            </Badge>
            <p className="max-w-64 break-words text-muted-foreground">{test.detail}</p>
          </div>
        )}
        {!test && provider.last_test_at && (
          <span className={provider.last_test_ok ? "text-muted-foreground" : "text-destructive"}>
            {provider.last_test_ok ? "OK" : "Failed"} · {formatWhen(provider.last_test_at)}
          </span>
        )}
        {!test && !provider.last_test_at && <span className="text-muted-foreground">{"—"}</span>}
      </TableCell>
      <TableCell className="whitespace-nowrap">
        <Button
          size="sm"
          variant="outline"
          className="mr-1.5"
          aria-label={`Test ${provider.label}`}
          disabled={test === "running" || provider.source === "unset"}
          onClick={onTest}
        >
          Test
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="mr-1.5"
          aria-label={`Edit ${provider.label}`}
          disabled={!enabled || Boolean(provider.error)}
          onClick={onEdit}
        >
          Edit
        </Button>
        {(provider.source === "db" || provider.error) && (
          <Button
            size="sm"
            variant="destructive"
            aria-label={`Revert ${provider.label} to .env`}
            onClick={onRevert}
          >
            Revert to .env
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}

const SELECT_CLASS =
  "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 font-mono text-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-focus";

function SecretEditDialog({
  provider,
  onSaved,
  onClose,
}: {
  provider: Provider;
  onSaved: () => void;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const isLlm = provider.key === "llm";
  // Dialog hanya dipasang saat terbuka (key per provider), jadi state awal otomatis segar tiap
  // dibuka dan nilai yang diketik tidak bertahan sesudah ditutup.
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(provider.fields.map((f) => [f.name, f.secret ? "" : (f.value ?? "")])),
  );
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

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
  const canSave = (typedSecret || changedPlain) && password.length > 0 && notice === null;

  const mutation = useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.PUT("/api/secrets/{provider}", {
        params: { path: { provider: provider.key } },
        body: { fields: buildFields(), current_password: password },
      });
      if (!response.ok || !data) throw new Error(errorMessage(error, response.status));
      return data;
    },
    onSuccess: async (data) => {
      onSaved();
      await queryClient.invalidateQueries({ queryKey: SECRETS_KEY });
      if (data.probe && data.probe.status !== "OK") {
        // Tersimpan, tapi vendor tidak (atau belum) membuktikan key-nya valid: jangan menutup
        // dialog seolah semuanya beres. Password dan key yang diketik dibuang dari state.
        setPassword("");
        setValues((v) => Object.fromEntries(provider.fields.map((f) => [f.name, f.secret ? "" : v[f.name]])));
        setNotice(
          `Saved, but the key was not verified (${data.probe.status}): ${data.probe.detail}`,
        );
        return;
      }
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  function renderField(f: Field) {
    const id = `secret-${provider.key}-${f.name}`;
    return (
      <div key={f.name} className="space-y-1.5">
        <Label htmlFor={id} className="text-sm font-medium text-muted-foreground">
          {fieldLabel(f.name)}
          {f.secret && f.last4 && (
            <span className="ml-1 font-code normal-case">(current …{f.last4})</span>
          )}
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
            onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
            className="font-mono text-xs"
          />
        ) : f.choices.length > 0 ? (
          <select
            id={id}
            value={values[f.name] ?? ""}
            onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
            className={SELECT_CLASS}
          >
            {f.choices.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        ) : (
          <Input
            id={id}
            autoComplete="off"
            spellCheck={false}
            value={values[f.name] ?? ""}
            onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
            className="font-mono text-xs"
          />
        )}
        {isLlm && f.name === "url" && (
          <p className="text-xs text-muted-foreground">
            Leave empty for the vendor default. Outside dev the server only accepts allow-listed
            https hosts.
          </p>
        )}
      </div>
    );
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !mutation.isPending && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading">Edit {provider.label}</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground">
          The new key is tested against the vendor before it is saved. A failed test saves nothing.
        </p>
        {provider.fields.map(renderField)}
        <div className="space-y-1.5">
          <Label htmlFor={`secret-${provider.key}-password`} className="text-sm font-medium text-muted-foreground">
            Your password (to confirm)
          </Label>
          <Input
            id={`secret-${provider.key}-password`}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="font-mono text-xs"
          />
        </div>
        {error && (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}
        {notice && (
          <p role="status" className="text-xs text-warning">
            {notice}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={mutation.isPending} onClick={onClose}>
            {notice ? "Close" : "Cancel"}
          </Button>
          <Button
            onClick={() => {
              setError(null);
              mutation.mutate();
            }}
            disabled={mutation.isPending || !canSave}
          >
            {mutation.isPending ? "Testing and saving…" : "Test and save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SecretRevertDialog({
  provider,
  onSaved,
  onClose,
}: {
  provider: Provider;
  onSaved: () => void;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      const { error, response } = await api.DELETE("/api/secrets/{provider}", {
        params: { path: { provider: provider.key } },
        body: { current_password: password },
      });
      if (!response.ok) throw new Error(errorMessage(error, response.status));
    },
    onSuccess: async () => {
      onSaved();
      await queryClient.invalidateQueries({ queryKey: SECRETS_KEY });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Dialog open onOpenChange={(open) => !open && !mutation.isPending && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="font-heading">Revert {provider.label} to .env</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground">
          The key saved here is deleted and the value in <span className="font-mono">.env</span>{" "}
          is used again. That value may be outdated or already revoked at the vendor.
        </p>
        <div className="space-y-1.5">
          <Label htmlFor={`revert-${provider.key}-password`} className="text-sm font-medium text-muted-foreground">
            Your password (to confirm)
          </Label>
          <Input
            id={`revert-${provider.key}-password`}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="font-mono text-xs"
          />
        </div>
        {error && (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={mutation.isPending} onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              setError(null);
              mutation.mutate();
            }}
            disabled={mutation.isPending || !password}
          >
            Revert
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
