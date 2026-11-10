import { countryName } from "@/lib/countries";
import type { SpikeEntry, SpikesResponse } from "@/lib/api/loose-types";

export type SpikeCategory = "actor" | "industry" | "country" | "overall";

export interface CategorizedSpike extends SpikeEntry {
  category: SpikeCategory;
  /** Kunci unik baris: satu entity bisa punya beberapa hari spike. */
  value: string;
}

/** Urutan tetap grup di mode Grouped (spec 6.3), bukan urutan kemunculan setelah sort z. */
export const CATEGORY_ORDER: readonly SpikeCategory[] = ["actor", "industry", "country", "overall"];

export const CATEGORY_META: Record<SpikeCategory, { section: string; noun: string; tile: string; entityType?: string }> = {
  actor: { section: "THREAT ACTOR SPIKES", noun: "threat actor", tile: "Threat actors", entityType: "intrusion-set" },
  industry: { section: "INDUSTRY SPIKES", noun: "industry", tile: "Industries", entityType: "identity" },
  country: { section: "COUNTRY SPIKES", noun: "country", tile: "Countries", entityType: "location" },
  overall: { section: "OVERALL SPIKES", noun: "overall volume", tile: "Overall volume" },
};

const withCategory = (list: SpikeEntry[], category: SpikeCategory): CategorizedSpike[] =>
  list.map((s) => ({ ...s, category, value: `${category}|${s.entity}|${s.date}` }));

/** Gabung empat array API menjadi satu daftar berkategori. Urutan di dalam kategori dipertahankan. */
export function categorize(d: SpikesResponse): CategorizedSpike[] {
  return [
    ...withCategory(d.threat_actors, "actor"),
    ...withCategory(d.industries, "industry"),
    ...withCategory(d.countries, "country"),
    ...withCategory(d.overall, "overall"),
  ];
}

export const byZ = (a: SpikeEntry, b: SpikeEntry) => b.z_score - a.z_score;

/** Nama tampilan: kode negara jadi nama negara; overall tidak punya entity. */
export function spikeName(s: CategorizedSpike): string {
  if (s.category === "overall") return "Overall volume";
  return s.category === "country" ? countryName(s.entity) : s.entity;
}

/** Deret harian untuk spike terpilih; undefined bila entity tidak ada di blok `daily`. */
export function dailySeries(d: SpikesResponse, s: CategorizedSpike): number[] | undefined {
  switch (s.category) {
    case "actor":
      return d.daily.threat_actors[s.entity];
    case "industry":
      return d.daily.industries[s.entity];
    case "country":
      return d.daily.countries[s.entity];
    default:
      return d.daily.overall;
  }
}
