"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { PasswordPolicy } from "@/lib/api/loose-types";
import { noClientRetry, unwrap } from "@/lib/scrapers/queries";

export const DEFAULT_POLICY: PasswordPolicy = {
  min_length: 8,
  require_upper: true,
  require_lower: true,
  require_number: true,
  require_symbol: true,
};

/** Port `loadPolicy()`/`_pwPolicy` lama -- `/api/auth/policy` publik (gak
 * butuh auth), dipakai buat live-validate password di client SEBELUM
 * submit (server tetap validasi ulang, ini cuma UX). Dipakai bareng di
 * Add User, Reset Password (admin), dan Change Password (diri sendiri). */
export function usePasswordPolicyQuery() {
  return useQuery({
    queryKey: ["auth", "policy"],
    queryFn: async () => {
      const r = await api.GET("/api/auth/policy");
      return unwrap(r, "Could not load the password policy") as unknown as PasswordPolicy;
    },
    retry: noClientRetry,
    staleTime: 60_000,
  });
}

export function usePasswordPolicy() {
  return usePasswordPolicyQuery().data ?? DEFAULT_POLICY;
}

/** Daftar aturan untuk checklist live (`PasswordRules`): hanya aturan yang
 * diminta policy (panjang selalu), regex sama dengan yang dipakai server. */
export function passwordRules(
  pw: string,
  p: PasswordPolicy,
): { label: string; met: boolean }[] {
  const min = p.min_length || 8;
  const rules = [{ label: `At least ${min} characters`, met: pw.length >= min }];
  if (p.require_upper) rules.push({ label: "An uppercase letter", met: /[A-Z]/.test(pw) });
  if (p.require_lower) rules.push({ label: "A lowercase letter", met: /[a-z]/.test(pw) });
  if (p.require_number) rules.push({ label: "A number", met: /[0-9]/.test(pw) });
  if (p.require_symbol) rules.push({ label: "A symbol", met: /[^A-Za-z0-9]/.test(pw) });
  return rules;
}

export function allRulesMet(pw: string, p: PasswordPolicy): boolean {
  return passwordRules(pw, p).every((r) => r.met);
}
