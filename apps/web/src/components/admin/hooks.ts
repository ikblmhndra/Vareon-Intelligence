"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { AdminUser, AuditLogEntry, Client, Permission, Role } from "@/lib/api/loose-types";
import { noClientRetry, unwrap } from "@/lib/scrapers/queries";

/**
 * Endpoint `/api/auth/users`, `/api/roles`, `/api/roles/permissions`,
 * `/api/clients` semua balikin `list[dict[str,object]]` polos di backend
 * (gak ada `response_model`) -- `as unknown as X[]` di sini nge-cast
 * ke shape yang dicek langsung dari `_serialize()` masing-masing router
 * (`auth.py::get_users`, `roles.py`, `clients.py`), bukan tebakan.
 * Semua lewat `unwrap` (body 502 kosong lolos `if (error)`) dan tanpa retry 4xx.
 * "Sekarang" dibaca di dalam `queryFn`, tidak saat render.
 */

/** Pesan galat query/mutasi Admin; 403 diterjemahkan jadi permission yang kurang. */
export function adminErrorMessage(e: unknown, permission: string): string {
  if (e instanceof Error && e.cause === 403) return `You need the ${permission} permission`;
  return e instanceof Error ? e.message : String(e);
}

export function useAdminUsers(enabled = true) {
  return useQuery({
    queryKey: ["admin", "users"],
    enabled,
    queryFn: async () => ({
      users: unwrap(await api.GET("/api/auth/users"), "Failed to load users") as unknown as AdminUser[],
      nowMs: Date.now(),
    }),
    retry: noClientRetry,
  });
}

export function useRoles(enabled = true) {
  return useQuery({
    queryKey: ["admin", "roles"],
    enabled,
    queryFn: async () =>
      unwrap(await api.GET("/api/roles"), "Failed to load roles") as unknown as Role[],
    retry: noClientRetry,
  });
}

export function usePermissions() {
  return useQuery({
    queryKey: ["admin", "permissions"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/roles/permissions"),
        "Failed to load permissions",
      ) as unknown as Permission[],
    retry: noClientRetry,
  });
}

export function useClients(enabled = true) {
  return useQuery({
    queryKey: ["admin", "clients"],
    enabled,
    queryFn: async () =>
      unwrap(await api.GET("/api/clients"), "Failed to load clients") as unknown as Client[],
    retry: noClientRetry,
  });
}

export function useAuditLog(
  params: { page: number; pageSize: number; user: string; action: string },
  enabled = true,
) {
  return useQuery({
    queryKey: ["admin", "audit-log", params],
    enabled,
    queryFn: async () => {
      const data = unwrap(
        await api.GET("/api/auth/audit-log", {
          params: {
            query: {
              page: params.page,
              page_size: params.pageSize,
              user: params.user || undefined,
              action: params.action || undefined,
            },
          },
        }),
        "Failed to load audit log",
      ) as unknown as { logs: AuditLogEntry[]; total: number };
      return { ...data, dayStartMs: new Date().setHours(0, 0, 0, 0) };
    },
    retry: noClientRetry,
  });
}

export function useApiTokens(enabled = true) {
  return useQuery({
    queryKey: ["admin", "api-tokens"],
    enabled,
    queryFn: async () => ({
      tokens: unwrap(await api.GET("/api/api-tokens"), "Failed to load API tokens") as components["schemas"]["ApiTokenOut"][],
      nowMs: Date.now(),
    }),
    retry: noClientRetry,
  });
}

export function useSecrets(enabled = true) {
  return useQuery({
    queryKey: ["admin", "secrets"],
    enabled,
    queryFn: async () =>
      unwrap(await api.GET("/api/secrets"), "Failed to load third-party keys") as components["schemas"]["SecretsStatusOut"],
    retry: noClientRetry,
  });
}
