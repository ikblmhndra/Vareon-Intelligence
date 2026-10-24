/**
 * `X-Client-ID` yang boleh diteruskan proxy ke `cti-api`. Sejak 0.8.4 API menolak (403) client yang
 * bukan milik user; cookie `cti_client_id` bisa basi (ganti akun di browser yang sama, client
 * dicabut admin), dan tanpa saringan ini semua halaman langsung gagal. Payload JWT dibaca TANPA
 * verifikasi: ini hanya memutuskan header mana yang diteruskan, `cti-api` tetap memverifikasi
 * token dan menegakkan aksesnya sendiri.
 */
export function allowedClientHeader(token: string | undefined, clientId: string | null): string | null {
  if (!clientId || !token) return null;
  const payload = decodePayload(token);
  if (!payload) return null;
  if (payload.role === "superadmin") return clientId;
  const ids = Array.isArray(payload.client_ids) ? payload.client_ids : [payload.client_id];
  return ids.includes(clientId) ? clientId : null;
}

function decodePayload(token: string): { role?: string; client_ids?: unknown; client_id?: unknown } | null {
  const part = token.split(".")[1];
  if (!part) return null;
  try {
    return JSON.parse(Buffer.from(part, "base64url").toString("utf8"));
  } catch {
    return null;
  }
}
