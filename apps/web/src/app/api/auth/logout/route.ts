import { NextResponse } from "next/server";

import { clearSessionCookie, getSessionToken } from "@/lib/auth/session";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function POST(): Promise<NextResponse> {
  // Cabut token di server (denylist Redis) sebelum cookie dihapus, supaya token yang sudah
  // bocor/tersalin tidak berlaku sampai kedaluwarsa. Best-effort: gagal tidak menghalangi logout.
  const token = await getSessionToken();
  if (token) {
    await fetch(`${API_BASE_URL}/api/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => undefined);
  }
  await clearSessionCookie();
  return NextResponse.json({ ok: true });
}
