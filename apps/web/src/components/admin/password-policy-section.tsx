"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { usePasswordPolicy } from "@/lib/auth/password-policy";
import type { PasswordPolicy } from "@/lib/api/loose-types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Draft = Partial<PasswordPolicy> & { force_all_change?: boolean };

/** Port section "Password Policy" + `savePolicy()`. `require_admin` di
 * backend (`PUT /api/auth/policy`).
 *
 * Form field pakai pola "derived state" (`override` cuma nyimpen yang
 * USER UBAH, fallback ke `policy` dari server) -- BUKAN `useEffect` yang
 * nge-sync `policy` (query async) ke `useState` lokal begitu data dateng,
 * itu persis pola yang kena `react-hooks/set-state-in-effect` di
 * `AuthProvider` Grup A. */
export function PasswordPolicySection() {
  const queryClient = useQueryClient();
  const policy = usePasswordPolicy();
  const [override, setOverride] = useState<Draft>({});
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const minLength = override.min_length ?? policy.min_length;
  const upper = override.require_upper ?? policy.require_upper;
  const lower = override.require_lower ?? policy.require_lower;
  const numberReq = override.require_number ?? policy.require_number;
  const symbol = override.require_symbol ?? policy.require_symbol;
  const forceAll = override.force_all_change ?? false;

  const saveMutation = useMutation({
    mutationFn: async () => {
      const { data, response } = await api.PUT("/api/auth/policy", {
        body: {
          min_length: minLength,
          require_upper: upper,
          require_lower: lower,
          require_number: numberReq,
          require_symbol: symbol,
          force_all_change: forceAll,
        },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${response.status}`);
      }
      return data;
    },
    onSuccess: (data) => {
      setOverride({});
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["auth", "policy"] });
      const flagged = (data as { flagged_users?: number })?.flagged_users;
      setStatus(`Saved${flagged ? ` · ${flagged} users flagged` : ""}`);
      setTimeout(() => setStatus(null), 3500);
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-semibold text-foreground">
          Password Policy
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3.5">
        <div className="flex flex-wrap gap-3.5">
          <div className="space-y-1.5">
            <Label className="text-sm font-medium text-muted-foreground">Min Length</Label>
            <Input
              type="number" aria-label="Min length"
              min={4}
              max={128}
              value={minLength}
              onChange={(e) => setOverride({ ...override, min_length: parseInt(e.target.value, 10) || 8 })}
              className="w-20 font-mono text-xs"
            />
          </div>
          <label className="flex cursor-pointer items-center gap-1.5 self-end pb-1.5 text-xs">
            <Checkbox
              checked={upper}
              onCheckedChange={(c) => setOverride({ ...override, require_upper: c === true })}
            />{" "}
            Require Uppercase
          </label>
          <label className="flex cursor-pointer items-center gap-1.5 self-end pb-1.5 text-xs">
            <Checkbox
              checked={lower}
              onCheckedChange={(c) => setOverride({ ...override, require_lower: c === true })}
            />{" "}
            Require Lowercase
          </label>
          <label className="flex cursor-pointer items-center gap-1.5 self-end pb-1.5 text-xs">
            <Checkbox
              checked={numberReq}
              onCheckedChange={(c) => setOverride({ ...override, require_number: c === true })}
            />{" "}
            Require Number
          </label>
          <label className="flex cursor-pointer items-center gap-1.5 self-end pb-1.5 text-xs">
            <Checkbox
              checked={symbol}
              onCheckedChange={(c) => setOverride({ ...override, require_symbol: c === true })}
            />{" "}
            Require Symbol
          </label>
        </div>
        <label className="flex cursor-pointer items-center gap-1.5 text-xs">
          <Checkbox
            checked={forceAll}
            onCheckedChange={(c) => setOverride({ ...override, force_all_change: c === true })}
          />{" "}
          Force all users to change password on next login
        </label>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
            Save Policy
          </Button>
          {status && <span className="font-mono text-xs text-muted-foreground">{status}</span>}
        </div>
      </CardContent>
    </Card>
  );
}
