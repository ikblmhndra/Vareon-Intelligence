import { NextResponse } from "next/server";

import { clientIpHeaders } from "@/lib/auth/client-ip";
import { setSessionCookie } from "@/lib/auth/session";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

/**
 * Terima {username, password} dari form login (Client Component), teruskan
 * ke `cti-api` `POST /api/auth/login`, taruh `access_token` hasilnya ke
 * cookie httpOnly -- browser gak pernah pegang token mentah. Field selain
 * token (`role`/`client_ids`/`force_pw_change`/dst) dibalikin apa adanya
 * di body response biar `AuthProvider` bisa langsung populate state tanpa
 * round-trip tambahan ke `/api/auth/me`.
 */
export async function POST(request: Request): Promise<NextResponse> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE_URL}/api/auth/login`, {
      method: "POST",
      // `clientIpHeaders`: rate limit login di API di-key per IP -- tanpa
      // ini semua orang kelihatan datang dari IP container `web`.
      headers: { "Content-Type": "application/json", ...clientIpHeaders(request) },
      body: JSON.stringify(body),
    });
  } catch {
    return NextResponse.json({ detail: "cti-api unreachable" }, { status: 502 });
  }

  const payload = await upstream.json().catch(() => null);

  if (!upstream.ok || !payload?.access_token) {
    // `Retry-After` dari limiter API diteruskan supaya form bisa menghitung mundur 429.
    const retryAfter = upstream.headers.get("Retry-After");
    return NextResponse.json(payload ?? { detail: "Login failed" }, {
      status: upstream.status || 401,
      ...(retryAfter ? { headers: { "Retry-After": retryAfter } } : {}),
    });
  }

  await setSessionCookie(payload.access_token as string);

  delete payload.access_token;
  return NextResponse.json(payload);
}
