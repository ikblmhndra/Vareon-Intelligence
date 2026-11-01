import type { QueryClient } from "@tanstack/react-query";

/** `detail` API bisa string (409) atau daftar error validasi (422); tampilkan apa adanya. */
export function errorDetail(err: unknown, fallback: string): string {
  const detail = (err as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (d as { msg?: string }).msg ?? JSON.stringify(d)).join("; ");
  }
  return fallback;
}

/** Muat ulang detail, daftar, dan semua sub-daftar entity (merge/split memindahkan semuanya). */
export function invalidateEntity(qc: QueryClient, ...ids: number[]) {
  for (const id of ids) {
    for (const key of [
      "entity",
      "entity-totals",
      "entity-relationships",
      "entity-stories",
      "entity-indicators",
      "entity-cves",
      "entity-attack",
      "entity-timeline",
    ]) {
      void qc.invalidateQueries({ queryKey: [key, id] });
    }
  }
  void qc.invalidateQueries({ queryKey: ["entities"] });
}

/** Normalisasi nama alias: trim, huruf kecil, spasi beruntun jadi satu. */
export const normAlias = (s: string) => s.trim().toLowerCase().replace(/\s+/g, " ");

/** Alias selain nama entity sendiri (dan external_id untuk technique), dibanding lewat `normAlias`. */
export function otherAliases(aliases: string[], name: string, externalId?: string | null): string[] {
  const own = new Set([normAlias(name), ...(externalId ? [normAlias(externalId)] : [])]);
  return aliases.filter((a) => !own.has(normAlias(a)));
}
