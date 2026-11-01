import type { EntityChipItem } from "@/components/entities/entity-chip";
import { countryName } from "@/lib/countries";

/** Id teknik ATT&CK di awal teks ("T1566", "T1566.001 Phishing"). */
const TECHNIQUE_ID = /^T\d{4}(\.\d{3})?\b/i;
const CVE_ID = /CVE-\d{4}-\d+/gi;

/**
 * Chip dari nilai berupa nama saja (respons v1 tanpa `entity_id`), diselesaikan lewat halaman resolve.
 * Negara: kode ISO jadi `name` (resolve lewat external_id) dan label nama negara; teknik yang diawali
 * id memakai id itu sebagai `name` dan teks utuh sebagai label; sisanya apa adanya.
 */
export function nameChip(type: string, value: string): EntityChipItem {
  if (type === "location" && /^[A-Za-z]{2}$/.test(value)) {
    const code = value.toUpperCase();
    return { type, name: code, label: countryName(code) };
  }
  if (type === "attack-pattern") {
    const m = TECHNIQUE_ID.exec(value);
    if (m) return { type, name: m[0].toUpperCase(), label: value };
  }
  return { type, name: value };
}

export function nameChips(type: string, values: string[] | undefined): EntityChipItem[] {
  return (values ?? []).filter(Boolean).map((v) => nameChip(type, v));
}

/** Semua id CVE (unik, huruf besar) di dalam teks bebas. */
export function cveIdsIn(text: string): string[] {
  return [...new Set((text.match(CVE_ID) ?? []).map((c) => c.toUpperCase()))];
}
