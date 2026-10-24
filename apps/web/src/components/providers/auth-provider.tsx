"use client";

import { createContext, useCallback, useContext } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { getActiveClientId, setActiveClientId } from "@/lib/auth/client-id";

export interface AuthUser {
  username: string;
  role: string;
  client_ids: string[];
  client_countries: string[];
  clients_map: Record<string, string[]>;
  /** Wajib ganti password dulu: server menolak semua endpoint lain sampai selesai. */
  force_pw_change?: boolean;
}

interface AuthContextValue {
  user: AuthUser | null;
  status: "loading" | "authenticated" | "unauthenticated";
  login: (username: string, password: string) => Promise<{ ok: true } | { ok: false; detail: string }>;
  logout: () => Promise<void>;
}

const ME_QUERY_KEY = ["auth", "me"] as const;

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

  const { data: user, isPending } = useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: fetchMe,
    staleTime: 60_000,
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
      return { ok: true };
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    queryClient.setQueryData(ME_QUERY_KEY, null);
    router.push("/login");
  }, [queryClient, router]);

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
