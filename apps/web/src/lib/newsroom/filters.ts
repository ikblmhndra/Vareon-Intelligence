"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";

export interface NewsroomFilters {
  search: string;
  dateStart: string;
  dateEnd: string;
  /** Kode ISO alpha-2, `null` = semua negara. */
  country: string | null;
  industry: string;
  actor: string;
  /** "Insiden saja": teruskan `confirmed_only` ke endpoint yang mendukungnya. */
  incidentOnly: boolean;
}

/** Tanggal LOKAL (Y-M-D); `toISOString` menggeser ke UTC dan bisa mundur sehari. */
function isoDate(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

/** Chip N = N hari kalender terakhir TERMASUK hari ini (tanggal lokal): `dateStart` =
 * hari ini - (N-1). API menghitung jendela `(hari ini - start) + 1` = N. `0` = "Semua".
 * `dateEnd` sengaja selalu kosong. */
export function periodStart(days: number): string {
  if (!days) return "";
  const d = new Date();
  d.setDate(d.getDate() - (days - 1));
  return isoDate(d);
}

/** Default "7 hari terakhir" -- newsroom lama memang selalu mulai ke-scope 7 hari. */
export function defaultNewsroomFilters(): NewsroomFilters {
  return {
    search: "",
    dateStart: periodStart(7),
    dateEnd: "",
    country: null,
    industry: "",
    actor: "",
    incidentOnly: false,
  };
}

/**
 * Port `/api/filters` (isi dropdown country/industry/actor). Country di
 * sini kode ISO alpha-2 langsung dari `FilterOptions.countries` --
 * `variantToCanonical`/`expandCountry`/`/api/country-groups` legacy
 * SENGAJA gak diport, `routers/articles.py` sendiri bilang itu peta
 * nama-negara-bebas-teks yang udah obsolete (skema baru `ArticleCountry.
 * country_code` udah ISO alpha-2 dari enrichment, gak ada lagi varian
 * nama yang perlu di-grup di layer API).
 */
export function useFilterOptions() {
  return useQuery({
    queryKey: ["newsroom", "filter-options"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/filters");
      if (error) throw error;
      return data;
    },
    staleTime: 5 * 60_000,
  });
}
