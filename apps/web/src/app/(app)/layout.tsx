"use client";

import { useEffect } from "react";

import { AppSidebar, AppTopbar } from "@/components/app-header";
import { ChangePasswordDialog } from "@/components/change-password-dialog";
import { useAuth } from "@/components/providers/auth-provider";
import { Skeleton } from "@/components/ui/skeleton";

/** Kerangka shell selama `/api/auth/me` belum menjawab: bentuknya meniru sidebar + topbar +
 * konten, jadi halaman tidak berkedip dari teks "Loading..." ke layout penuh. */
function ShellSkeleton() {
  return (
    <div role="status" className="flex min-h-dvh">
      <span className="sr-only">Loading...</span>
      <aside className="hidden w-64 shrink-0 flex-col gap-8 border-r border-border px-4 py-6 lg:flex">
        <div className="flex items-center gap-3 px-2">
          <Skeleton className="size-10 rounded-full" />
          <Skeleton className="h-9 w-24" />
        </div>
        <div className="flex flex-col gap-1">
          {Array.from({ length: 10 }, (_, i) => (
            <Skeleton key={i} className="h-11 rounded-full" />
          ))}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="h-[65px] border-b border-border" />
        <div className="mx-auto w-full max-w-[1600px] space-y-6 p-4 sm:p-8">
          <Skeleton className="h-9 w-56" />
          <Skeleton className="h-36 w-full rounded-3xl" />
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-28 rounded-2xl" />
            ))}
          </div>
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
    if (status === "unauthenticated") {
      void logout();
    }
  }, [status, logout]);

  if (status === "loading") {
    return <ShellSkeleton />;
  }

  if (status !== "authenticated") {
    return null;
  }

  if (user?.force_pw_change) {
    return <ChangePasswordDialog open forced onOpenChange={() => undefined} />;
  }

  return (
    <div className="flex min-h-dvh">
      <a
        href="#main-content"
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:top-3 focus-visible:left-3 focus-visible:z-50 focus-visible:rounded-full focus-visible:bg-primary focus-visible:px-4 focus-visible:py-2 focus-visible:text-sm focus-visible:font-medium focus-visible:text-primary-foreground focus-visible:shadow-md focus-visible:outline-none"
      >
        Skip to content
      </a>
      <AppSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <AppTopbar />
        <main
          id="main-content"
          tabIndex={-1}
          className="mx-auto w-full max-w-[1600px] flex-1 p-4 outline-none sm:p-8"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
