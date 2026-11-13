"use client";

import { createContext, useCallback, useContext } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { getActiveClientId, setActiveClientId } from "@/lib/auth/client-id";
import {
  markSigningOut,
  resetSessionExpired,
  useSessionState,
} from "@/lib/auth/session-expired";

export interface AuthUser {
  username: string;
  role: string;
  client_ids: string[];
  client_countries: string[];
  clients_map: Record<string, string[]>;
  /** Wajib ganti password dulu: server menolak semua endpoint lain sampai selesai. */
  force_pw_change?: boolean;
  /** Permission efektif role user (0.8.4); lihat `useCan` di `lib/auth/permissions.ts`. */
  permissions?: string[];
  /** Waktu sign-in token ini (dari `iat`); null untuk token lama tanpa `iat`. */
  signed_in_at?: string | null;
}

interface AuthContextValue {
  user: AuthUser | null;
  status: "loading" | "authenticated" | "unauthenticated";
  login: (username: string, password: string) => Promise<{ ok: true } | { ok: false; detail: string }>;
  logout: (redirectTo?: string) => Promise<void>;
}

export const ME_QUERY_KEY = ["auth", "me"] as const;

const AuthContext = createContext<AuthContextValue | null>(null);

async function fetchMe(): Promise<AuthUser | null> {
  const res = await fetch("/api/auth/me", { cache: "no-store" });
  if (!res.ok) return null;
  const user = (await res.json()) as AuthUser;
  syncActiveClient(user);
  return user;
}

/** Cookie client aktif yang bukan milik user (ganti akun di browser yang sama, client dicabut)
 * dikembalikan ke client pertama user, supaya switcher dan header `X-Client-ID` cocok dengan akses
 * yang sebenarnya. Superadmin boleh memilih client mana pun. */
function syncActiveClient(user: AuthUser): void {
  const active = getActiveClientId();
  if (user.role === "superadmin" || !user.client_ids.length) return;
  if (!active || !user.client_ids.includes(active)) setActiveClientId(user.client_ids[0]);
}

/** `useQuery` (bukan `useEffect`+`useState` manual) buat `/api/auth/me` --
 * setState di dalam bare `useEffect` kena flag `react-hooks/set-state-in-
 * effect` (React 19 lint baru, KETEMU pas `pnpm lint` Grup A). TanStack
 * Query udah nanganin "fetch on mount" dengan cara yang gak numbuk
 * aturan itu (state-nya diurus internal Query, bukan efek kita), plus
 * gratis cache-nya buat `login()`/`logout()` nulis balik tanpa perlu
 * `useState` terpisah. */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const router = useRouter();

  // Setelah sesi berakhir cookie sudah dihapus: refetch (mis. window-focus) akan menjadikan user
  // `null` dan melepas halaman dari bawah dialog, jadi query dimatikan selain saat `active`.
  const sessionState = useSessionState();
  const { data: user, isPending } = useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: fetchMe,
    staleTime: 60_000,
    enabled: sessionState === "active",
  });

  const status: AuthContextValue["status"] = isPending
    ? "loading"
    : user
      ? "authenticated"
      : "unauthenticated";

  const login = useCallback<AuthContextValue["login"]>(
    async (username, password) => {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        return { ok: false, detail: body?.detail ?? "Login failed" };
      }
      const loggedInUser = (await res.json()) as AuthUser;
      syncActiveClient(loggedInUser);
      queryClient.setQueryData(ME_QUERY_KEY, loggedInUser);
      resetSessionExpired();
      return { ok: true };
    },
    [queryClient],
  );

  const logout = useCallback<AuthContextValue["logout"]>(
    async (redirectTo) => {
      // Sebelum request apa pun: 401 yang mendarat selama logout disengaja tidak membuka dialog.
      markSigningOut();
      await fetch("/api/auth/logout", { method: "POST" });
      queryClient.setQueryData(ME_QUERY_KEY, null);
      const target = redirectTo ? "/login?redirect=" + encodeURIComponent(redirectTo) : "/login";
      // Sudah di URL itu (`/login` yang memanggil `logout(redirect)`): push akan me-reset judul layout.
      if (target !== location.pathname + location.search) router.push(target);
    },
    [queryClient, router],
  );

  return (
    <AuthContext.Provider value={{ user: user ?? null, status, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth() must be used inside <AuthProvider>");
  return ctx;
}
