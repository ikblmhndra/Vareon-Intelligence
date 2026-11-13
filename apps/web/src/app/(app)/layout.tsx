"use client";

import { useEffect } from "react";

import { AppShell, SHELL_COLUMN } from "@/components/app-shell/app-shell";
import { ChangePasswordDialog } from "@/components/change-password-dialog";
import { useAuth } from "@/components/providers/auth-provider";
import { SessionExpiredHost, signInAgain } from "@/components/session-expired";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";
import { getSessionState } from "@/lib/auth/session-expired";

/** Kerangka shell selama `/api/auth/me` belum menjawab: bentuknya meniru utility bar + masthead +
 * konten (`AppShell`), jadi halaman tidak berkedip dari teks "Loading..." ke layout penuh. */
function ShellSkeleton() {
  return (
    <div role="status" className="flex min-h-dvh flex-col">
      <span className="sr-only">Loading...</span>
      <div className={SHELL_COLUMN}>
        <div className="flex h-[54px] items-center justify-between border-b-2 border-foreground">
          <Skeleton className="h-3 w-48" />
          <Skeleton className="size-8 rounded-full" />
        </div>
        <div className="flex items-end justify-between border-b border-foreground pt-[18px] pb-3.5">
          <Skeleton className="h-[46px] w-40" />
          <Skeleton className="mb-2 hidden h-4 w-[560px] lg:block" />
          <Skeleton className="h-8 w-20 lg:hidden" />
        </div>
      </div>
      <div className={`${SHELL_COLUMN} space-y-6 py-6 lg:py-8`}>
        <Skeleton className="h-9 w-56" />
        <Skeleton className="h-36 w-full rounded-xl" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
      </div>
    </div>
  );
}

/** Shell buat SEMUA route ber-auth (9 route Fase 8) -- `proxy.ts` udah
 * nge-redirect optimistic di edge kalau cookie gak ada sama sekali, guard
 * di sini nangkep kasus SISANYA: cookie ada tapi ternyata invalid/expired
 * (baru ketauan pas `/api/auth/me` beneran dipanggil -- proxy.ts SENGAJA
 * gak decode JWT, lihat docstring situ). */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { status, user, logout } = useAuth();

  useEffect(() => {
    // Cookie yang tidak valid HARUS dihapus dulu (`logout()` = POST /api/auth/logout lalu ke
    // /login). Cuma `router.replace("/login")` bikin loop: `proxy.ts` melempar /login + cookie
    // apa pun balik ke /dashboard.
    // Load penuh dengan cookie mati menyimpan tempat user (`?redirect=`); logout disengaja
    // (`signing-out`) harus berakhir di /login polos, jadi tidak membawa path user sebelumnya.
    if (status === "unauthenticated" && getSessionState() !== "signing-out") {
      void logout(location.pathname + location.search);
    }
  }, [status, logout]);

  if (status === "loading") {
    return <ShellSkeleton />;
  }

  if (status !== "authenticated") {
    // Efek di atas sedang (atau sudah gagal) keluar; jangan tampilkan layar kosong. Tombol = load
    // penuh ke /login (hapus cookie dulu), bukan efek, jadi tidak membuat loop baru.
    return (
      <div className="mx-auto max-w-xl p-6">
        <Notice
          tone="warning"
          title="You are signed out."
          action={<Button onClick={() => void signInAgain()}>Sign in</Button>}
        >
          Sign in to continue.
        </Notice>
      </div>
    );
  }

  if (user?.force_pw_change) {
    return <ChangePasswordDialog open forced onOpenChange={() => undefined} />;
  }

  return (
    <AppShell>
      <SessionExpiredHost />
      {children}
    </AppShell>
  );
}
