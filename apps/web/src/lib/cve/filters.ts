"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export type DateBasis = "published" | "detected";

export const DATE_BASIS_LABELS: Record<DateBasis, string> = {
  published: "Published",
  detected: "Detected",
};

export interface CveFilters {
  search: string;
  severity: string;
  tech: string;
  dateStart: string;
  dateEnd: string;
  /** Dasar tanggal From/To: tanggal terbit CVE, atau hari (WIB) CVE pertama terdeteksi. Dipakai
   * sama oleh list, stats, dan export Excel supaya angka dan isi file selalu cocok. */
  dateBasis: DateBasis;
  includeFp: boolean;
  unackedOnly: boolean;
}

export function defaultCveFilters(): CveFilters {
  return {
    search: "",
    severity: "",
    tech: "",
    dateStart: "",
    dateEnd: "",
    dateBasis: "published",
    includeFp: false,
    unackedOnly: false,
  };
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
