"use client";

import { useEffect, useState } from "react";
import { useQuery, type QueryClient, type UseQueryResult } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type PIROut = components["schemas"]["PIROut"];
export type PIRCriteria = components["schemas"]["PIRCriteria"];
export type PIRPreviewOut = components["schemas"]["PIRPreviewOut"];

/** Tab status halaman PIR. "Closed" = nilai tersimpan `archived` (tidak ada migrasi nilai). */
export type PirStatusTab = "active" | "paused" | "archived";

export const PIR_STATUS_TABS: readonly { value: PirStatusTab; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "paused", label: "Paused" },
  { value: "archived", label: "Closed" },
];

export function isPirStatusTab(v: string | null): v is PirStatusTab {
  return v === "active" || v === "paused" || v === "archived";
}

/** Baris kriteria di kartu dan detail, urutan sesuai mockup; hanya baris yang terisi yang ditampilkan.
 * `code` = nilai berupa id (TTP) yang harus memakai `font-code`. */
export const PIR_CRITERIA_ROWS: readonly { key: keyof PIRCriteria; label: string; code?: boolean }[] = [
  { key: "threat_actors", label: "THREAT ACTORS" },
  { key: "malware", label: "MALWARE" },
  { key: "industries", label: "INDUSTRIES" },
  { key: "countries", label: "COUNTRIES" },
  { key: "ttps", label: "TTPS", code: true },
  { key: "keywords", label: "KEYWORDS" },
  { key: "news_types", label: "NEWS TYPES" },
];

/** Kelas tint lencana prioritas per nada `pirPriority` (ditulis utuh supaya Tailwind menemukannya). */
export const PIR_PRIORITY_CHIP = {
  destructive: "bg-destructive/15 text-destructive-text",
  warning: "bg-warning/15 text-warning-text",
  info: "bg-info/15 text-info-text",
  neutral: "bg-panel text-foreground",
} as const;

async function fetchPirs(includeCampaigns: boolean): Promise<PIROut[]> {
  const { data, error } = await api.GET("/api/pir", {
    params: { query: includeCampaigns ? { include_campaigns: true } : {} },
  });
  if (error) throw error;
  return data;
}

/** Daftar PIR (cakupan + RFI tertaut). Halaman merender dari sini; kampanye datang terpisah. */
export function usePirs(): UseQueryResult<PIROut[]> {
  return useQuery({ queryKey: ["pir", "list"], queryFn: () => fetchPirs(false) });
}

/** Varian `include_campaigns=true`: clustering kampanye di backend mahal (detik di dev), jadi diambil di
 * latar dengan kunci sendiri dan `staleTime` 10 menit; hanya baris "Campaigns matched" yang menunggunya. */
export function usePirCampaigns(): UseQueryResult<PIROut[]> {
  return useQuery({
    queryKey: ["pir", "list", "campaigns"],
    queryFn: () => fetchPirs(true),
    staleTime: 10 * 60 * 1000,
  });
}

/** Semua kunci PIR (daftar, varian kampanye, pratinjau) segar lagi setelah simpan/hapus. */
export function invalidatePirs(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: ["pir"] });
}

/** Jumlah artikel 90 hari terakhir yang cocok kriteria, untuk footer dialog. Debounce 500 ms atas JSON
 * kriteria (kunci query = JSON itu, jadi kriteria yang sama tidak dihitung ulang). `settling` = ketikan
 * terbaru belum dikirim, supaya footer bisa menampilkan spinner alih-alih angka lama seolah final. */
export function usePirPreview(
  criteria: PIRCriteria,
  enabled: boolean,
): UseQueryResult<PIRPreviewOut> & { settling: boolean } {
  const key = JSON.stringify(criteria);
  const [debounced, setDebounced] = useState(key);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(key), 500);
    return () => clearTimeout(t);
  }, [key]);
  const query = useQuery({
    queryKey: ["pir", "preview", debounced],
    enabled,
    retry: false,
    queryFn: async () => {
      // `days` punya default di backend, tapi tipe hasil openapi-typescript mewajibkannya: kirim eksplisit.
      const { data, error } = await api.POST("/api/pir/preview", {
        body: { criteria: JSON.parse(debounced) as PIRCriteria, days: 90 },
      });
      if (error) throw error;
      return data;
    },
  });
  return Object.assign(query, { settling: key !== debounced });
}
