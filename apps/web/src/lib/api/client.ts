"use client";

import createClient from "openapi-fetch";

import type { paths } from "./schema";
import { getActiveClientId } from "@/lib/auth/client-id";
import { getSessionState, markSessionExpired } from "@/lib/auth/session-expired";

/**
 * `baseUrl` nunjuk ke proxy Next.js (`/api/proxy`), BUKAN `cti-api`
 * langsung -- browser gak pernah pegang JWT (httpOnly cookie), lihat
 * `docs/PROGRESS.md` Fase 8 keputusan #3. `schema.d.ts` di-generate dari
 * `docs/openapi.json` (`pnpm run gen:api`) -- path/method/body/response
 * semua ke-typecheck, drift backend ketahuan pas build, bukan runtime.
 */
/** Selama sesi sudah berakhir (atau sedang logout) tidak ada request ke jaringan: jawaban 401
 * sintetis, supaya polling berhenti dan penulisan gagal dengan kalimat yang sama di toast. */
const guardedFetch = (request: Request): Promise<Response> =>
  getSessionState() !== "active"
    ? Promise.resolve(
        new Response(JSON.stringify({ detail: "Your session has ended. Sign in again." }), {
          status: 401,
          headers: { "content-type": "application/json" },
        }),
      )
    : fetch(request);

export const api = createClient<paths>({ baseUrl: "/api/proxy", fetch: guardedFetch });

/** Token habis di tengah sesi: tandai dulu (sinkron, sebelum await, supaya 401 paralel lain
 * tidak ikut masuk), lalu hapus cookie (kalau tidak, `proxy.ts` melempar /login balik ke
 * /dashboard). Tidak ada navigasi: dialog di `SessionExpiredHost` yang mengantar user. */
async function handleExpiry(response: Response): Promise<void> {
  if (response.status === 401 && typeof window !== "undefined" && getSessionState() === "active") {
    markSessionExpired();
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
  }
}

/** `fetch` untuk unduhan/stream lewat `/api/proxy` yang tidak bisa lewat `api`: pakai penjaga sesi
 * dan penanganan 401 yang sama (fetch mentah menembus penjaga). `X-Client-ID` dipasang di sini juga,
 * kecuali pemanggil sudah mengisinya. */
export async function proxyFetch(input: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  const clientId = getActiveClientId();
  if (clientId && !headers.has("X-Client-ID")) headers.set("X-Client-ID", clientId);
  const response = await guardedFetch(new Request(input, { ...init, headers }));
  await handleExpiry(response);
  return response;
}

api.use({
  onRequest({ request }) {
    const clientId = getActiveClientId();
    if (clientId) {
      request.headers.set("X-Client-ID", clientId);
    }
    return request;
  },
  async onResponse({ response }) {
    await handleExpiry(response);
    return response;
  },
});
