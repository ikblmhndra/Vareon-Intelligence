"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { useAuth } from "@/components/providers/auth-provider";
import { policyHint, usePasswordPolicy, validatePasswordClient } from "@/lib/auth/password-policy";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * Ganti password diri sendiri -- port `openSelfPwModal()`/
 * `doSelfPwChange()` (`usermgmt.js`, dipicu klik username di header lama).
 * Gap nyata dari Grup A: sebelum ini gak ada cara user ganti password
 * sendiri dari UI sama sekali. Dipasang di `UserMenu` (Grup C, numpang
 * `usePasswordPolicy()`/`validatePasswordClient()` yang dibangun buat
 * Admin Reset Password/Add User).
 */
export function ChangePasswordDialog({
  open,
  onOpenChange,
  forced = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Akun ditandai `force_pw_change`: dialog tidak bisa ditutup, hanya ganti password / sign out. */
  forced?: boolean;
}) {
  const policy = usePasswordPolicy();
  const { logout } = useAuth();
  const [currentPw, setCurrentPw] = useState("");
  const [pw, setPw] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      const { response } = await api.POST("/api/auth/change-password", {
        body: { current_password: currentPw, new_password: pw },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        const msg = Array.isArray(body?.detail)
          ? body.detail.map((e: { msg?: string }) => e.msg).join("; ")
          : body?.detail || `HTTP ${response.status}`;
        throw new Error(msg);
      }
    },
    onSuccess: () => {
      setCurrentPw("");
      setPw("");
      onOpenChange(false);
      // Server mencabut semua sesi lama setelah ganti password -> login ulang dengan yang baru.
      void logout();
    },
    onError: (e: Error) => setError(e.message),
  });

  function handleSubmit() {
    setError(null);
    const pwErr = validatePasswordClient(pw, policy);
    if (pwErr) return setError(pwErr);
    mutation.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={forced ? () => undefined : onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="font-heading">Change Password</DialogTitle>
        </DialogHeader>
        {forced && (
          <p className="text-xs text-muted-foreground">
            Akun ini wajib mengganti password sebelum melanjutkan.
          </p>
        )}
        <div className="space-y-1.5">
          <Label htmlFor="current-password" className="text-sm font-medium text-muted-foreground">
            Current Password
          </Label>
          <Input
            id="current-password"
            type="password"
            autoComplete="current-password"
            value={currentPw}
            onChange={(e) => setCurrentPw(e.target.value)}
            className="font-mono text-xs"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="new-password" className="text-sm font-medium text-muted-foreground">
            New Password <span className="normal-case opacity-70">({policyHint(policy)})</span>
          </Label>
          <Input
            id="new-password"
            type="password"
            autoComplete="new-password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            className="font-mono text-xs"
          />
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => (forced ? void logout() : onOpenChange(false))}>
            {forced ? "Sign out" : "Cancel"}
          </Button>
          <Button onClick={handleSubmit} disabled={mutation.isPending || !currentPw || !pw}>
            Update
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
