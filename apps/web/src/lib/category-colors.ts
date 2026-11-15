/** Warna kategori yang konsisten antar grafik: nama -> slot `--chart-(i+1)` (10 slot).
 * Tanpa import supaya bisa dites langsung dengan `node --test`. */

const SLOT_COUNT = 10;

/** Kunci sudah dinormalkan (huruf kecil, spasi dirapatkan). */
export const KNOWN_CATEGORY_SLOTS: Readonly<Record<string, number>> = {
  // Disalin dari GLOBAL_NEWS_TYPES (src/lib/newsroom/news-types.ts): 6 nama, slot unik.
  "global": 0,
  "security technology & best practices": 1,
  "vendor report article": 2,
  "data breach article": 3,
  "tech stack article": 4,
  "ot article": 5,

  // Label industri lama yang dipakai LLM/analis (kunci _LABEL_TO_SECTOR di
  // packages/cti-core/src/cti_core/entity/sectors.py): 10 teratas, slot unik.
  "finance & insurance": 0,
  "healthcare & life sciences": 1,
  "government & public sector": 2,
  "information technology & software": 3,
  "telecommunications": 4,
  "energy & utilities": 5,
  "manufacturing & industrial": 6,
  "retail & e-commerce": 7,
  "education & research": 8,
  "transportation & logistics": 9,
  // Lebih dari 10 label: sisanya boleh berbagi slot (wrap).
  "critical infrastructure": 6,
  "general": 7,

  // Nama sektor vocab STIX (nilai SECTORS di sectors.py), searah dengan label lama di atas.
  "financial services": 0,
  "healthcare": 1,
  "government": 2,
  "technology": 3,
  "energy": 5,
  "manufacturing": 6,
  "retail": 7,
  "education": 8,
  "transportation": 9,
};

function normalize(name: string): string {
  return name.trim().replace(/\s+/g, " ").toLowerCase();
}

/** FNV-1a 32-bit: hash string yang stabil antar proses. */
function fnv1a(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

/** Slot warna 0..9 (pakai `var(--chart-${i + 1})`). Nama dikenal lewat peta tetap, sisanya lewat hash. */
export function categoryColorIndex(name: string): number {
  const key = normalize(name);
  const known = KNOWN_CATEGORY_SLOTS[key];
  if (known !== undefined) return known;
  return fnv1a(key) % SLOT_COUNT;
}
