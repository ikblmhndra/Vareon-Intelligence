"use client";

import { useCallback } from "react";

import { useAuth } from "@/components/providers/auth-provider";

/**
 * `can("manage_newsletter")` -- apakah user boleh memakai aksi yang dijaga permission itu di API
 * (`require_permission`, 0.8.4). Daftarnya dari `/api/auth/me` (`permissions`). Tombol yang tidak
 * boleh dipakai disembunyikan supaya user tidak menekan sesuatu yang akan dibalas 403.
 *
 * Hanya kenyamanan tampilan: API tetap menegakkan izinnya sendiri. Kalau API lama belum mengirim
 * `permissions`, semua aksi dianggap boleh (perilaku sebelum 0.8.4) supaya tidak ada yang hilang.
 */
export function useCan(): (permission: string) => boolean {
  const { user } = useAuth();
  const permissions = user?.permissions;
  return useCallback(
    (permission: string) => {
      if (!user) return false;
      if (user.role === "superadmin" || !permissions) return true;
      return permissions.includes(permission);
    },
    [user, permissions],
  );
}
