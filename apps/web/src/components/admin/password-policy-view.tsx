"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { AdminFrame, AdminPageHeading } from "@/components/admin/admin-frame";
import { adminErrorMessage } from "@/components/admin/hooks";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { PasswordRules } from "@/components/password-rules";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { api } from "@/lib/api/client";
import type { PasswordPolicy } from "@/lib/api/loose-types";
import { usePasswordPolicyQuery } from "@/lib/auth/password-policy";
import { unwrap } from "@/lib/scrapers/queries";

// Batas bawah UI 8 (P8); API mengizinkan 4-128 (`PolicySettings.min_length`).
const MIN_FLOOR = 8;
const MIN_CEIL = 128;
const FORCE_HELP =
  "Flags every account except those with the admin role, superadmins included. Sessions that are open now keep working until they end.";
const RULES = [
  ["require_upper", "Require an uppercase letter"],
  ["require_lower", "Require a lowercase letter"],
  ["require_number", "Require a number"],
  ["require_symbol", "Require a symbol"],
] as const;

function PolicyForm({ initial }: { initial: PasswordPolicy }) {
  const queryClient = useQueryClient();
  const [minText, setMinText] = useState(String(initial.min_length));
  const [rules, setRules] = useState({
    require_upper: initial.require_upper,
    require_lower: initial.require_lower,
    require_number: initial.require_number,
    require_symbol: initial.require_symbol,
  });
  const [forceAll, setForceAll] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const minLength = Number(minText);
  const minOk = Number.isInteger(minLength) && minLength >= MIN_FLOOR && minLength <= MIN_CEIL;

  const save = useMutation({
    mutationFn: async () => {
      const r = await api.PUT("/api/auth/policy", {
        body: { min_length: minLength, ...rules, force_all_change: forceAll },
      });
      return unwrap(r, "Could not save the policy") as unknown as { flagged_users?: number };
    },
    onSuccess: (data) => {
      const flagged = data.flagged_users ?? 0;
      toast.success(
        forceAll ? `Policy saved · ${flagged} users must change their password` : "Policy saved",
      );
      setForceAll(false);
      setConfirmOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["auth", "policy"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (e) => {
      setConfirmOpen(false);
      setError(adminErrorMessage(e, "manage_policy"));
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!minOk || save.isPending) return;
    setError(null);
    if (forceAll) setConfirmOpen(true);
    else save.mutate();
  }

  return (
    <form onSubmit={submit} className="grid items-start gap-6 lg:grid-cols-2">
      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="pw-min-length">Minimum length</Label>
          <Input
            id="pw-min-length"
            type="number"
            min={MIN_FLOOR}
            max={MIN_CEIL}
            value={minText}
            onChange={(e) => setMinText(e.target.value)}
            aria-invalid={!minOk}
            aria-describedby="pw-min-help"
            className="w-24 font-code"
          />
          <p
            id="pw-min-help"
            className={minOk ? "text-xs text-muted-foreground" : "text-xs text-destructive-text"}
          >
            8 or more. Longer beats more symbol rules.
          </p>
        </div>
        {RULES.map(([key, label]) => (
          <div key={key} className="flex items-center gap-2">
            <Checkbox
              id={`pw-${key}`}
              checked={rules[key]}
              onCheckedChange={(c) => setRules({ ...rules, [key]: c === true })}
            />
            <Label htmlFor={`pw-${key}`}>{label}</Label>
          </div>
        ))}
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Checkbox
              id="pw-force-all"
              checked={forceAll}
              onCheckedChange={(c) => setForceAll(c === true)}
              aria-describedby="pw-force-help"
            />
            <Label htmlFor="pw-force-all">Make every user change their password at next sign-in</Label>
          </div>
          <p id="pw-force-help" className="pl-6 text-xs text-muted-foreground">
            {FORCE_HELP}
          </p>
        </div>
        {error && (
          <Notice tone="destructive" title="Could not save the policy">
            {error}
          </Notice>
        )}
        <Button type="submit" loading={save.isPending} disabled={!minOk || save.isPending}>
          Save policy
        </Button>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-2xs tracking-wide text-muted-foreground">WHAT USERS SEE</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <PasswordRules password="" policy={{ min_length: minLength, ...rules }} />
          <p className="text-xs text-muted-foreground">Shown under every new-password field.</p>
        </CardContent>
      </Card>
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Make every user change their password?"
        description={FORCE_HELP}
        confirmLabel="Save and flag users"
        confirmLoading={save.isPending}
        onConfirm={() => save.mutate()}
      />
    </form>
  );
}

export function PasswordPolicyView() {
  const policy = usePasswordPolicyQuery();
  let body;
  if (policy.isPending) {
    body = (
      <div role="status">
        <Skeleton aria-hidden className="h-64 w-full" />
        <span className="sr-only">Loading the password policy</span>
      </div>
    );
  } else if (policy.isError) {
    body = (
      <StatePanel
        variant="error"
        title="Failed to load the password policy"
        action={<Button variant="outline" size="sm" onClick={() => void policy.refetch()}>Retry</Button>}
      />
    );
  } else {
    body = <PolicyForm initial={policy.data} />;
  }
  return (
    <AdminFrame page="password-policy">
      <AdminPageHeading title="Password policy" description="Applies at the next password change" />
      {body}
    </AdminFrame>
  );
}
