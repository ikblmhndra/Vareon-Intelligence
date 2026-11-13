"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { ME_QUERY_KEY, useAuth } from "@/components/providers/auth-provider";
import { allRulesMet, usePasswordPolicy } from "@/lib/auth/password-policy";
import { unwrap } from "@/lib/scrapers/queries";
import { PasswordRules } from "@/components/password-rules";
import { Notice } from "@/components/ui/notice";
import { Button } from "@/components/ui/button";
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

/**
 * Ganti password diri sendiri -- port `openSelfPwModal()`/
 * `doSelfPwChange()` (`usermgmt.js`, dipicu klik username di header lama).
 * Gap nyata dari Grup A: sebelum ini gak ada cara user ganti password
 * sendiri dari UI sama sekali. Dipasang di `AvatarMenu` (dulu `UserMenu`, Grup C; numpang
 * `usePasswordPolicy()`/`validatePasswordClient()` yang dibangun buat
 * Admin Reset Password/Add User).
 */
export function ChangePasswordDialog({
  open,
  onOpenChange,
  forced = false,
  finalFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Akun ditandai `force_pw_change`: dialog tidak bisa ditutup, hanya ganti password / sign out. */
  forced?: boolean;
  /** Ke mana fokus kembali saat dialog menutup. Dibuka dari item menu avatar yang sudah di-unmount,
   * jadi tanpa ini fokus jatuh ke `<body>`. */
  finalFocus?: React.RefObject<HTMLElement | null>;
}) {
  const policy = usePasswordPolicy();
  const { logout } = useAuth();
  const queryClient = useQueryClient();
  const [currentPw, setCurrentPw] = useState("");
  const [pw, setPw] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Dialog dipakai juga oleh fallback layout (app) saat /login tidak bisa menangani sendiri.
  // Sign-out gagal (POST logout) tidak boleh diam: cookie masih ada, jadi beri tahu user.
  async function signOutAfterChange() {
    // `logout()` kembali tanpa melempar bila POST gagal; cache user tetap terisi = belum keluar.
    try {
      await logout();
    } catch {
      /* ditangani di bawah */
    }
    if (queryClient.getQueryData(ME_QUERY_KEY)) {
      toast.error("Could not sign you out. Use Sign out in the menu, then sign in again.");
    }
  }

  const mutation = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/auth/change-password", {
          body: { current_password: currentPw, new_password: pw },
        }),
        "Could not change the password",
      ),
    onSuccess: () => {
      setCurrentPw("");
      setPw("");
      onOpenChange(false);
      toast.success("Password changed. Sign in with your new password.");
      // Server mencabut semua sesi lama setelah ganti password -> login ulang dengan yang baru.
      void signOutAfterChange();
    },
    onError: (e: Error) => setError(e.message),
  });

  function handleSubmit() {
    setError(null);
    mutation.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={forced ? () => undefined : onOpenChange}>
      <DialogContent className="sm:max-w-sm" finalFocus={finalFocus}>
        <DialogHeader>
          <DialogTitle className="font-heading">
            {forced ? "Choose a new password" : "Change password"}
          </DialogTitle>
          <DialogDescription>
            {forced
              ? "Your account needs a new password, after an administrator reset or a policy change. Pick one to continue."
              : "You are signed out everywhere afterwards and sign in with the new password."}
          </DialogDescription>
        </DialogHeader>
        {error && (
          <div role="alert">
            <Notice tone="destructive" title={error} />
          </div>
        )}
        <div className="space-y-1.5">
          <Label htmlFor="current-password" className="text-sm font-medium text-muted-foreground">
            Current password
          </Label>
          <Input
            id="current-password"
            type="password"
            autoComplete="current-password"
            value={currentPw}
            onChange={(e) => setCurrentPw(e.target.value)}
            className="font-code text-sm"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="new-password" className="text-sm font-medium text-muted-foreground">
            New password
          </Label>
          <Input
            id="new-password"
            type="password"
            autoComplete="new-password"
            aria-describedby="new-password-rules"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            className="font-code text-sm"
          />
          <PasswordRules id="new-password-rules" password={pw} policy={policy} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => (forced ? void signOutAfterChange() : onOpenChange(false))}>
            {forced ? "Sign out" : "Cancel"}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={mutation.isPending || !currentPw || !allRulesMet(pw, policy)}
          >
            {mutation.isPending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
