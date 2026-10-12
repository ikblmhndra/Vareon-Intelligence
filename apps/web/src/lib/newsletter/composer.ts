import type { components } from "@/lib/api/schema";

type Article = components["schemas"]["ArticleOut"];
type SuggestionItem = components["schemas"]["NewsletterSuggestionItem"];
type SuggestionReason = components["schemas"]["NewsletterSuggestionReason"];
type RequestBody = components["schemas"]["NewsletterSectionsBody"];

/**
 * Logika murni composer newsletter (ROADMAP #22, PR 9): slot tier, batas, pemindahan artikel,
 * penggabungan saran, dan bentuk request. Tanpa React dan tanpa IO supaya tiap aturan bisa dicek
 * sendiri; komponen hanya memanggil fungsi di sini lalu `setState` hasilnya.
 *
 * Satu artikel ada di paling banyak SATU slot. Nama slot sama persis dengan field request tier
 * (`highlights`, `<section>_full`, `<section>_compact`), jadi `buildRequestBody` tinggal memetakan.
 */

export type SectionName = "apac" | "global_news" | "indonesia";
export type Tier = "highlight" | "full" | "compact";
export type SlotKey =
  | "highlights"
  | "apac_full"
  | "apac_compact"
  | "global_news_full"
  | "global_news_compact"
  | "indonesia_full"
  | "indonesia_compact";

/** Cermin `MAX_HIGHLIGHTS`/`MAX_FULL_PER_SECTION`/`MAX_COMPACT_PER_SECTION` di
 * `cti_api.schemas.newsletter`. API menjawab 400 kalau terlewati, jadi kalau angka di server
 * disetel ulang (titik mulai, disetel setelah edisi pertama) ubah di dua tempat ini. */
export const MAX_HIGHLIGHTS = 3;
export const MAX_FULL_PER_SECTION = 4;
export const MAX_COMPACT_PER_SECTION = 15;

/** Judul bagian = judul di email (Executive Summary, Highlights, Asia Pacific, Global,
 * Indonesia); lihat ROADMAP #22 "Headings are English". */
export const SECTIONS: { key: SectionName; label: string }[] = [
  { key: "apac", label: "Asia Pacific" },
  { key: "global_news", label: "Global" },
  { key: "indonesia", label: "Indonesia" },
];

export interface SlotDef {
  key: SlotKey;
  /** `null` untuk blok Highlights. */
  section: SectionName | null;
  tier: Tier;
  cap: number;
  /** Nama untuk menu dan pesan, mis. "Asia Pacific · full cards". */
  label: string;
}

export const SLOTS: SlotDef[] = [
  { key: "highlights", section: null, tier: "highlight", cap: MAX_HIGHLIGHTS, label: "Highlights" },
  ...SECTIONS.flatMap((s): SlotDef[] => [
    {
      key: `${s.key}_full`,
      section: s.key,
      tier: "full",
      cap: MAX_FULL_PER_SECTION,
      label: `${s.label} · full cards`,
    },
    {
      key: `${s.key}_compact`,
      section: s.key,
      tier: "compact",
      cap: MAX_COMPACT_PER_SECTION,
      label: `${s.label} · Also Noted`,
    },
  ]),
];

export const SLOT_BY_KEY = Object.fromEntries(SLOTS.map((s) => [s.key, s])) as Record<SlotKey, SlotDef>;

export interface ComposerState {
  slots: Record<SlotKey, Article[]>;
  /** Catatan analis per artikel (`str(article.id)`), sama bentuknya dengan field `notes`. */
  notes: Record<string, string>;
  /** Alasan saran per artikel, diisi saat saran dipakai; artikel dari Newsroom tidak punya. */
  reasons: Record<number, SuggestionReason[]>;
}

export function emptyComposer(): ComposerState {
  return {
    slots: Object.fromEntries(SLOTS.map((s) => [s.key, []])) as unknown as Record<SlotKey, Article[]>,
    notes: {},
    reasons: {},
  };
}

export function placedCount(state: ComposerState): number {
  return SLOTS.reduce((n, s) => n + state.slots[s.key].length, 0);
}

export function isComposerEmpty(state: ComposerState): boolean {
  return placedCount(state) === 0;
}

export function placedIds(state: ComposerState): Set<number> {
  return new Set(SLOTS.flatMap((s) => state.slots[s.key].map((a) => a.id)));
}

export function locate(state: ComposerState, articleId: number): SlotKey | null {
  return SLOTS.find((s) => state.slots[s.key].some((a) => a.id === articleId))?.key ?? null;
}

export type Change = { ok: true; state: ComposerState } | { ok: false; message: string };

function withSlot(state: ComposerState, key: SlotKey, articles: Article[]): ComposerState {
  return { ...state, slots: { ...state.slots, [key]: articles } };
}

/** Pesan saat batas menolak: menyebut slotnya dan jalan keluarnya, bukan sekadar "penuh". */
function capMessage(slot: SlotDef): string {
  const way =
    slot.tier === "highlight"
      ? "Move one to a section or remove it first."
      : slot.tier === "full"
        ? "Move one to Also Noted or remove it first."
        : "Remove one first.";
  return `${slot.label} is at its limit (${slot.cap} of ${slot.cap}). ${way}`;
}

function removeFrom(state: ComposerState, articleId: number): ComposerState {
  const from = locate(state, articleId);
  if (from === null) return state;
  return withSlot(
    state,
    from,
    state.slots[from].filter((a) => a.id !== articleId),
  );
}

/** Taruh `article` di `to`. Kalau sudah ada di slot lain ini jadi pemindahan. Slot penuh menolak
 * dan state TIDAK berubah (tidak ada yang tergeser diam-diam). */
export function place(state: ComposerState, article: Article, to: SlotKey): Change {
  const from = locate(state, article.id);
  if (from === to) return { ok: false, message: `Already in ${SLOT_BY_KEY[to].label}.` };
  if (state.slots[to].length >= SLOT_BY_KEY[to].cap) return { ok: false, message: capMessage(SLOT_BY_KEY[to]) };
  const without = removeFrom(state, article.id);
  return { ok: true, state: withSlot(without, to, [...without.slots[to], article]) };
}

/** Pindah artikel yang sudah ada di composer. */
export function move(state: ComposerState, articleId: number, to: SlotKey): Change {
  const from = locate(state, articleId);
  if (from === null) return { ok: false, message: "That article is not in the composer." };
  const article = state.slots[from].find((a) => a.id === articleId)!;
  return place(state, article, to);
}

export function remove(state: ComposerState, articleId: number): ComposerState {
  return removeFrom(state, articleId);
}

/** Ganti `outId` dengan `incoming` di posisi dan slot yang sama (kartu jadi kartu, baris jadi
 * baris). Mengganti dengan artikel yang sudah ada di composer ditolak: itu bukan penukaran. */
export function swap(state: ComposerState, outId: number, incoming: Article): Change {
  const at = locate(state, outId);
  if (at === null) return { ok: false, message: "That article is not in the composer." };
  if (locate(state, incoming.id) !== null) return { ok: false, message: "That article is already in the composer." };
  return {
    ok: true,
    state: withSlot(
      state,
      at,
      state.slots[at].map((a) => (a.id === outId ? incoming : a)),
    ),
  };
}

// ── Saran ───────────────────────────────────────────────────────────────────

/** Slot yang dicoba untuk satu item saran, berurutan: tier-nya dulu, lalu satu tier turun kalau
 * penuh. Highlight yang tidak muat jadi kartu penuh di section aslinya, kartu penuh yang tidak
 * muat jadi baris compact; compact yang tidak muat dibuang (dihitung `skipped`). */
function candidateSlots(item: SuggestionItem): SlotKey[] {
  const full: SlotKey = `${item.section}_full`;
  const compact: SlotKey = `${item.section}_compact`;
  if (item.tier === "highlight") return ["highlights", full, compact];
  if (item.tier === "full") return [full, compact];
  return [compact];
}

export interface MergeResult {
  state: ComposerState;
  /** Dipasang di slot tier aslinya. */
  added: number;
  /** Dipasang satu tier lebih rendah karena slot aslinya penuh. */
  demoted: number;
  /** Tidak muat di slot mana pun. */
  skipped: number;
  /** Sudah ada di composer, tidak disentuh. */
  alreadyPlaced: number;
  /** Ada di antrean analis (`skipIds`), dibiarkan di sana supaya mereka yang menempatkan. */
  left: number;
}

/**
 * Tambahkan item saran ke `state` tanpa menimpa apa pun yang sudah ada, menghormati batas slot.
 * `skipIds` = artikel yang JANGAN ditempatkan (antrean analis). Dipakai untuk "Merge" (state yang
 * ada, antrean sebagai `skipIds`) dan untuk "Use suggestion" / isi awal (state kosong, tanpa
 * `skipIds`). Urutan pemasangan mengikuti `rank`, jadi kalau batas memotong, yang terpotong yang
 * peringkatnya paling rendah.
 */
export function mergeSuggestion(
  state: ComposerState,
  items: SuggestionItem[],
  skipIds: ReadonlySet<number> = new Set(),
): MergeResult {
  let next = state;
  const result = { added: 0, demoted: 0, skipped: 0, alreadyPlaced: 0, left: 0 };
  for (const item of [...items].sort((a, b) => a.rank - b.rank)) {
    if (locate(next, item.article_id) !== null) {
      result.alreadyPlaced++;
      continue;
    }
    if (skipIds.has(item.article_id)) {
      result.left++;
      continue;
    }
    const candidates = candidateSlots(item);
    const target = candidates.find((k) => next.slots[k].length < SLOT_BY_KEY[k].cap);
    if (!target) {
      result.skipped++;
      continue;
    }
    if (target === candidates[0]) result.added++;
    else result.demoted++;
    next = withSlot(next, target, [...next.slots[target], item.article]);
    next = { ...next, reasons: { ...next.reasons, [item.article_id]: item.reasons } };
  }
  return { state: next, ...result };
}

/** Item saran yang belum ada di composer; sumber kolam "Suggested, not placed". */
export function unplacedSuggestion(state: ComposerState, items: SuggestionItem[]): SuggestionItem[] {
  const placed = placedIds(state);
  return [...items].filter((i) => !placed.has(i.article_id)).sort((a, b) => a.rank - b.rank);
}

// ── Request ─────────────────────────────────────────────────────────────────

/** Bagian `TemplateState` (komponen) yang masuk request; dideklarasikan di sini supaya lib tidak
 * mengimpor dari komponen. */
export interface TemplateFields {
  customCss: string;
  customIntro: string;
  customFooter: string;
  includeClusters: boolean;
  clusterDays: number;
}

export interface RequestExtras {
  language: "id" | "en";
  /** Periode saran yang dipakai; `null` = biarkan server memakai bulan kalender sebelumnya (WIB). */
  period: { start: string; end: string } | null;
  /** Id artikel yang ringkasannya dibangun ulang sekali (fetch + LLM). */
  regenerate: ReadonlySet<number>;
}

export type BuiltRequest = { ok: true; body: RequestBody } | { ok: false; message: string };

/** Composer -> body `preview`/`draft-email`. Validasi yang sama dengan composer lama: perlu satu
 * Highlight dan minimal satu artikel APAC atau Global (kartu atau baris). */
export function buildRequestBody(state: ComposerState, template: TemplateFields, extras: RequestExtras): BuiltRequest {
  const ids = (key: SlotKey) => state.slots[key].map((a) => a.id);
  if (state.slots.highlights.length === 0) return { ok: false, message: "Add a Highlight article first" };
  const regionalCount = (["apac_full", "apac_compact", "global_news_full", "global_news_compact"] as const).reduce(
    (n, k) => n + state.slots[k].length,
    0,
  );
  if (regionalCount === 0) return { ok: false, message: "Add at least one Asia Pacific or Global article" };

  const placed = placedIds(state);
  const notes = Object.fromEntries(
    Object.entries(state.notes).filter(([id, text]) => placed.has(Number(id)) && text.trim() !== ""),
  );
  // Hanya kartu yang punya ringkasan baru; baris compact tidak dibangun ulang.
  const cardIds = new Set(
    (["highlights", "apac_full", "global_news_full", "indonesia_full"] as const).flatMap((k) => ids(k)),
  );
  const body: RequestBody = {
    highlights: ids("highlights"),
    apac_full: ids("apac_full"),
    apac_compact: ids("apac_compact"),
    global_news_full: ids("global_news_full"),
    global_news_compact: ids("global_news_compact"),
    indonesia_full: ids("indonesia_full"),
    indonesia_compact: ids("indonesia_compact"),
    language: extras.language,
    regenerate: [...extras.regenerate].filter((id) => cardIds.has(id)),
    custom_css: template.customCss.trim(),
    custom_intro: template.customIntro.trim(),
    custom_footer: template.customFooter.trim(),
    notes,
    include_clusters: template.includeClusters,
    cluster_days: template.clusterDays,
    ...(extras.period ? { period_start: extras.period.start, period_end: extras.period.end } : {}),
  };
  return { ok: true, body };
}
