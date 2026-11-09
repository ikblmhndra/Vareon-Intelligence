"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export type DateBasis = "published" | "detected";

export const DATE_BASIS_LABELS: Record<DateBasis, string> = {
  published: "Published",
  detected: "Detected",
};

/** Tab daftar CVE (D5): Open = belum di-acknowledge, Acknowledged = sudah (bukan FP), fp = false positive. */
export type CveTab = "open" | "acked" | "fp";

export const CVE_TAB_OPTIONS = [
  { value: "open", label: "Open" },
  { value: "acked", label: "Acknowledged" },
  { value: "fp", label: "False positive" },
] as const;

export interface CveFilters {
  search: string;
  severity: string;
  tech: string;
  dateStart: string;
  dateEnd: string;
  /** Dasar tanggal From/To: tanggal terbit CVE, atau hari (WIB) CVE pertama terdeteksi. Dipakai
   * sama oleh list, stats, dan export Excel supaya angka dan isi file selalu cocok. */
  dateBasis: DateBasis;
  tab: CveTab;
}

export function defaultCveFilters(): CveFilters {
  return {
    search: "",
    severity: "",
    tech: "",
    dateStart: "",
    dateEnd: "",
    dateBasis: "detected",
    tab: "open",
  };
}

/** Parameter query bersama untuk list, stats, dan export Excel supaya angka tile, isi daftar, dan file
 * selalu cocok. Tab diterjemahkan ke `ack_filter` / `fp_only` (tab FP tidak punya `ack_filter`). */
export function cveQueryParams(filters: CveFilters) {
  return {
    severity: filters.severity ? [filters.severity] : undefined,
    tech: filters.tech ? [filters.tech] : undefined,
    search: filters.search || undefined,
    date_start: filters.dateStart || undefined,
    date_end: filters.dateEnd || undefined,
    date_basis: filters.dateBasis,
    ack_filter: filters.tab === "open" ? "unacked" : filters.tab === "acked" ? "acked" : undefined,
    fp_only: filters.tab === "fp" ? true : undefined,
  };
}

/** Filter selain tab: dipakai Empty B ("Clear filters") untuk tahu ada yang aktif. */
export function hasActiveCveFilters(filters: CveFilters): boolean {
  return Boolean(
    filters.search || filters.severity || filters.tech || filters.dateStart || filters.dateEnd,
  );
}

export const CVE_SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"] as const;

/** Port `_loadCveTechOptions()` (`cve.js:412`), `GET /api/cve/tech-list`. */
export function useCveTechOptions() {
  return useQuery({
    queryKey: ["cve", "tech-list"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/cve/tech-list");
      if (error) throw error;
      return data;
    },
  });
}
