"use client";

import createClient from "openapi-fetch";

import type { paths } from "./schema";
import { getActiveClientId } from "@/lib/auth/client-id";

/**
 * `baseUrl` nunjuk ke proxy Next.js (`/api/proxy`), BUKAN `cti-api`
 * langsung -- browser gak pernah pegang JWT (httpOnly cookie), lihat
 * `docs/PROGRESS.md` Fase 8 keputusan #3. `schema.d.ts` di-generate dari
 * `docs/openapi.json` (`pnpm run gen:api`) -- path/method/body/response
 * semua ke-typecheck, drift backend ketahuan pas build, bukan runtime.
 */
export const api = createClient<paths>({ baseUrl: "/api/proxy" });

let sessionExpiredHandled = false;

api.use({
  onRequest({ request }) {
    const clientId = getActiveClientId();
    if (clientId) {
      request.headers.set("X-Client-ID", clientId);
    }
    return request;
  },
  async onResponse({ response }) {
    // Token habis di tengah sesi: hapus cookie dulu (kalau tidak, `proxy.ts` melempar /login
    // balik ke /dashboard), baru ke halaman login.
    if (response.status === 401 && typeof window !== "undefined" && !sessionExpiredHandled) {
      sessionExpiredHandled = true;
      await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
      // reload penuh (bukan router.push): buang semua state klien; ini modul non-React.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/login";
    }
    return response;
  },
});
