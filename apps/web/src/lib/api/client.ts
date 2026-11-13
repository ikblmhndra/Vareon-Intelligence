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

api.use({
  onRequest({ request }) {
    const clientId = getActiveClientId();
    if (clientId) {
      request.headers.set("X-Client-ID", clientId);
    }
    return request;
  },
  async onResponse({ response }) {
    // Token habis di tengah sesi: tandai dulu (sinkron, sebelum await, supaya 401 paralel lain
    // tidak ikut masuk), lalu hapus cookie (kalau tidak, `proxy.ts` melempar /login balik ke
    // /dashboard). Tidak ada navigasi: dialog di `SessionExpiredHost` yang mengantar user.
    if (response.status === 401 && typeof window !== "undefined" && getSessionState() === "active") {
      markSessionExpired();
      await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    }
    return response;
  },
});
