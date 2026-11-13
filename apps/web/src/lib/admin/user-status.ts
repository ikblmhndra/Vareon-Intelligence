import type { AdminUser } from "@/lib/api/loose-types";

/** Status akun untuk chip; urutan cek penting: reset yang tertunda menang atas "belum pernah masuk". */
export function userStatus(u: AdminUser): "reset-pending" | "never" | "active" {
  if (u.force_pw_change) return "reset-pending";
  if (u.last_sign_in === null) return "never";
  return "active";
}
