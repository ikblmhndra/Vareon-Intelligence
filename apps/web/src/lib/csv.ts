import { proxyFetch } from "@/lib/api/client";
import { getActiveClientId } from "@/lib/auth/client-id";

const FORMULA_PREFIXES = ["=", "+", "-", "@", "\t", "\r"];

/** Satu sel CSV. Guard sama dengan `safe_cell` di `csv_export.py`: string berawalan `= + - @ TAB CR` diberi `'`
 * di depan supaya Excel/Sheets tidak mengeksekusinya sebagai formula (nilai berasal dari sumber luar). Sel yang
 * memuat koma, kutip, atau baris baru dibungkus kutip ganda. */
export function csvCell(v: unknown): string {
  let text: string;
  if (v === null || v === undefined) text = "";
  else if (typeof v === "boolean") text = v ? "true" : "false";
  else if (typeof v === "number") text = String(v);
  else if (v instanceof Date) text = v.toISOString();
  else if (Array.isArray(v)) text = v.map((x) => csvCell(x)).join(";");
  else {
    text = String(v);
    if (FORMULA_PREFIXES.some((p) => text.startsWith(p))) text = `'${text}`;
  }
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/** BOM UTF-8 (Excel membaca nama non-ASCII dengan benar) + baris dipisah `\r\n`, tiap baris diakhiri `\r\n`. */
export function toCsv(header: string[], rows: unknown[][]): string {
  return "﻿" + [header, ...rows].map((r) => r.map(csvCell).join(",") + "\r\n").join("");
}

function saveBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

/** Unduh teks CSV hasil `toCsv` di sisi klien (mis. Risk Matrix, yang responsnya sudah lengkap). */
export function downloadCsv(filename: string, text: string): void {
  saveBlob(new Blob([text], { type: "text/csv;charset=utf-8" }), filename);
}

function filenameFrom(disposition: string | null): string | null {
  if (!disposition) return null;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (star) {
    try {
      return decodeURIComponent(star[1]);
    } catch {
      /* jatuh ke bentuk biasa */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain ? plain[1] : null;
}

/** Unduh berkas dari endpoint export lewat proxy Next.js (browser tidak memanggil `cti-api` langsung, dan
 * cookie sesi httpOnly hanya terbaca proxy). `url` = path API (mis. `/api/sr/export?grade=A`); nama berkas dari
 * `Content-Disposition`, `fallbackName` bila tak ada. `truncated` = header `X-Export-Truncated` (export
 * terpotong di batas baris server) supaya pemanggil bisa memberi tahu pengguna. Melempar Error bila respons bukan 2xx. */
export async function downloadBlob(url: string, fallbackName: string): Promise<{ truncated: boolean }> {
  const target = url.startsWith("/api/proxy") ? url : `/api/proxy${url.startsWith("/") ? "" : "/"}${url}`;
  const headers: Record<string, string> = {};
  const clientId = getActiveClientId();
  if (clientId) headers["X-Client-ID"] = clientId;
  const res = await proxyFetch(target, { headers });
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  const blob = await res.blob();
  saveBlob(blob, filenameFrom(res.headers.get("Content-Disposition")) ?? fallbackName);
  return { truncated: res.headers.get("X-Export-Truncated")?.toLowerCase() === "true" };
}
