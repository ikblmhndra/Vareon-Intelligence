import { useQuery, type QueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type SREntry = components["schemas"]["SREntryOut"];

export type SrSortCol = "source_name" | "analyst_name" | "reliability_grade" | "last_updated";
export type SrSortDir = "asc" | "desc";

/** Label kolom urut untuk subjudul kartu ("sorted by last updated"). */
export const SR_SORT_LABEL: Record<SrSortCol, string> = {
  source_name: "source name",
  analyst_name: "analyst",
  reliability_grade: "reliability grade",
  last_updated: "last updated",
};

// Kelas ditulis utuh supaya Tailwind menemukannya. Tint + `text-X-text` (aturan "text on tints").
// A/B hijau, C kuning, D/E merah, F netral (tidak bisa dinilai).
const GRADE_CHIP: Record<string, string> = {
  A: "bg-success/15 text-success-text",
  B: "bg-success/15 text-success-text",
  C: "bg-warning/15 text-warning-text",
  D: "bg-destructive/15 text-destructive-text",
  E: "bg-destructive/15 text-destructive-text",
};

export function gradeChipClass(grade: string): string {
  return GRADE_CHIP[grade] ?? "bg-panel text-muted-foreground";
}

export interface SrLabels {
  reliability: Record<string, string>;
  credibility: Record<string, string>;
}

/** Peta label Admiralty dari `GET /api/sr/labels` (endpoint tanpa `response_model`, jadi dicast).
 * Kunci cache dibagi dengan dialog entri supaya satu permintaan melayani semuanya. */
export function useSrLabels() {
  return useQuery({
    queryKey: ["intelligence", "sr-labels"],
    staleTime: Infinity,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/sr/labels");
      if (error) throw error;
      return data as unknown as SrLabels;
    },
  });
}

/** Antrean "Needs review". Dipakai halaman (hitungan pil) dan tabel review dengan kunci yang sama;
 * `enabled` false tanpa `manage_sources` karena endpoint-nya menjawab 403. */
export function useSrReview(enabled: boolean) {
  return useQuery({
    queryKey: ["intelligence", "sr-review"],
    enabled,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/sr/review");
      if (error) throw error;
      return data.items;
    },
  });
}

/** Setelah tulis (tambah/ubah/hapus/konfirmasi) semua turunan data SR basi: daftar, statistik grade,
 * antrean review, dan daftar sumber belum bergrade di dialog tambah. */
export function invalidateSr(queryClient: QueryClient) {
  for (const key of ["sr-entries", "sr-stats", "sr-review", "ungraded-sources"]) {
    void queryClient.invalidateQueries({ queryKey: ["intelligence", key] });
  }
}
