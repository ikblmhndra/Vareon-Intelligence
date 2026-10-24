import { NextRequest, NextResponse } from "next/server";

import { allowedClientHeader } from "@/lib/auth/client-header";
import { clientIpHeaders } from "@/lib/auth/client-ip";
import { getSessionToken } from "@/lib/auth/session";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

/**
 * Satu-satunya jalur Client Component manggil `cti-api` -- lihat
 * `docs/PROGRESS.md` Fase 8 keputusan #3 (httpOnly cookie, BUKAN
 * localStorage). Cookie session cuma bisa dibaca DI SINI (server-side),
 * jadi tiap request ber-auth dari browser numpang route ini buat
 * dipasangin `Authorization: Bearer` sebelum diteruskan ke `cti-api`
 * beneran. `X-Client-ID` (multi-tenant, BUKAN rahasia) diteruskan hanya
 * bila client itu milik user di token (`allowedClientHeader`); nilainya
 * tetap ditentukan browser (cookie `cti_client_id`).
 *
 * Response DIBACA MENTAH (`arrayBuffer`, bukan `.json()`) -- beberapa
 * endpoint balikin binary (export Excel/DOCX, lihat `pir`/`cve` router)
 * yang gak boleh disentuh, `Content-Disposition` diteruskan biar nama
 * file unduhan tetep bener.
 */
async function proxy(request: NextRequest, path: string[]): Promise<NextResponse> {
  const token = await getSessionToken();
  const targetUrl = new URL(`${API_BASE_URL}/${path.join("/")}`);
  targetUrl.search = request.nextUrl.search;

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  if (token) headers.set("authorization", `Bearer ${token}`);
  // Header client yang bukan milik token dibuang (API akan 403), API jatuh ke client pertama user.
  const clientId = allowedClientHeader(token, request.headers.get("x-client-id"));
  if (clientId) headers.set("x-client-id", clientId);
  // IP klien asli (lihat client-ip.ts) -- tanpa ini API cuma lihat IP `web`.
  for (const [name, value] of Object.entries(clientIpHeaders(request))) headers.set(name, value);

  const init: RequestInit = { method: request.method, headers };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  let upstream: Response;
  try {
    upstream = await fetch(targetUrl, init);
  } catch {
    return NextResponse.json({ detail: "cti-api unreachable" }, { status: 502 });
  }

  const responseHeaders = new Headers();
  for (const name of ["content-type", "content-disposition"]) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }

  const body = await upstream.arrayBuffer();
  return new NextResponse(body, { status: upstream.status, headers: responseHeaders });
}

type Params = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, { params }: Params) {
  return proxy(request, (await params).path);
}
export async function POST(request: NextRequest, { params }: Params) {
  return proxy(request, (await params).path);
}
export async function PUT(request: NextRequest, { params }: Params) {
  return proxy(request, (await params).path);
}
export async function PATCH(request: NextRequest, { params }: Params) {
  return proxy(request, (await params).path);
}
export async function DELETE(request: NextRequest, { params }: Params) {
  return proxy(request, (await params).path);
}
