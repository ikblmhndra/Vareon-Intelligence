import { NextRequest, NextResponse } from "next/server";

/**
 * Guard route OPTIMISTIC doang (baca keberadaan cookie, GAK decode/
 * verifikasi JWT-nya di sini -- lihat dokumentasi Next.js: "should not
 * be used as a full session management or authorization solution").
 * Enforcement SEBENARNYA tetap di `cti-api` tiap kali proxy
 * (`app/api/proxy/[...path]`) manggil dia -- token invalid/expired
 * bakal ke-tolak 401 di situ, bukan di sini.
 *
 * File ini `proxy.ts` (BUKAN `middleware.ts`) -- Next.js 16 rename
 * konvensi ini, `middleware.ts` udah deprecated (lihat AGENTS.md yang
 * di-generate `next dev`, dan `node_modules/next/dist/docs/.../
 * middleware.md`).
 */
const SESSION_COOKIE = "cti_session";
const PUBLIC_PATHS = ["/login"];

export function proxy(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p));
  const hasSession = request.cookies.has(SESSION_COOKIE);

  if (!isPublic && !hasSession) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("redirect", pathname + request.nextUrl.search);
    return NextResponse.redirect(loginUrl);
  }

  if (pathname === "/login" && hasSession) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  // Semua route KECUALI: aset Next.js internal, Route Handler proxy/auth
  // sendiri (biar gak infinite-guard dirinya sendiri), file statis umum.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|ico)$).*)"],
};
