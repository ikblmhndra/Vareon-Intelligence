import { normalizeCountry } from "@/lib/dashboard/countries";
import { parseLocalDate } from "@/lib/format";
import { periodStart } from "@/lib/newsroom/filters";
import {
  newsroomPeriodInfo,
  parseNewsroomPeriod,
  type NewsroomPeriod,
} from "@/lib/newsroom/period";
import { RUBRIC_TITLES, rubricArticleQuery, type RubricKey } from "@/components/newsroom/rubric-queries";
import type { ArticlesQuery } from "@/components/newsroom/use-articles";

export type Grade = "A" | "B" | "C" | "D" | "E" | "F";

const GRADES: readonly Grade[] = ["A", "B", "C", "D", "E", "F"];

/** State tampilan All articles (spec 6.1); seluruhnya hidup di URL, tidak ada state komponen. */
export type AllState = {
  period: NewsroomPeriod;
  from: string | null;
  countries: string[];
  sector: string | null;
  sources: string[];
  grades: Grade[];
  rubric: RubricKey | null;
  actors: string[];
  ttps: string[];
  story: number | null;
  sort: "priority" | "recent";
  q: string;
  incidents: boolean;
  article: number | null;
  /** Select Group ransomware (`?group=`). */
  group: string | null;
  /** Select Industry ransomware (`?vindustry=`); bukan `industry`, itu alias `sector`. */
  vindustry: string | null;
};

type ArticleParams = NonNullable<ArticlesQuery>;

/** Param URL yang dikelola state ini; `view` dan lainnya tidak disentuh. `industry` ikut dihapus
 * saat menulis karena hanya alias `sector` (aturan 12). */
const MANAGED_KEYS = [
  "period",
  "from",
  "country",
  "sector",
  "industry",
  "source",
  "grade",
  "rubric",
  "actor",
  "ttp",
  "story",
  "sort",
  "q",
  "incidents",
  "article",
  "group",
  "vindustry",
] as const;

/** `?from=YYYY-MM-DD`: harus tanggal lokal yang valid (2026-13-40 atau 2026-02-30 ditolak, bukan
 * digeser). */
export function validFromParam(v: string | null): string | null {
  if (!v || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return null;
  const d = parseLocalDate(v);
  const [y, m, day] = v.split("-").map(Number);
  // Date menggeser tanggal tak ada (30 Feb -> 2 Mar), jadi cocokkan balik komponennya.
  const ok = d.getFullYear() === y && d.getMonth() + 1 === m && d.getDate() === day;
  return ok ? v : null;
}

/** Nilai param tak kosong (setelah trim), tanpa duplikat; `actor=` dan spasi saja diabaikan. */
function values(sp: URLSearchParams, key: string): string[] {
  return [...new Set(sp.getAll(key).map((v) => v.trim()).filter(Boolean))];
}

function one(sp: URLSearchParams, key: string): string | null {
  return sp.get(key)?.trim() || null;
}

/** Id positif utuh; "5x", "-1", "0", "1.5" dibuang. */
function positiveId(v: string | null): number | null {
  if (!v || !/^\d+$/.test(v.trim())) return null;
  const n = Number(v.trim());
  return Number.isSafeInteger(n) && n > 0 ? n : null;
}

function isRubricKey(v: string | null): v is RubricKey {
  return v !== null && Object.hasOwn(RUBRIC_TITLES, v);
}

/** Baca URL apa adanya; `sort` belum dipaksa recent oleh `story` supaya penulisan ulang tidak
 * membuat `sort=recent` menempel sesudah `story` dihapus. */
function readState(sp: URLSearchParams): AllState {
  const grades = new Set(values(sp, "grade").map((g) => g.toUpperCase()));
  const rubric = one(sp, "rubric");
  return {
    period: parseNewsroomPeriod(sp.get("period")),
    from: validFromParam(sp.get("from")),
    countries: [...new Set(values(sp, "country").map(normalizeCountry))],
    // Aturan 12: `sector` menang atas `industry` (alias lama dari `newsroomHref`).
    sector: one(sp, "sector") ?? one(sp, "industry"),
    sources: values(sp, "source"),
    grades: GRADES.filter((g) => grades.has(g)),
    rubric: isRubricKey(rubric) ? rubric : null,
    actors: values(sp, "actor"),
    ttps: values(sp, "ttp"),
    story: positiveId(sp.get("story")),
    sort: sp.get("sort") === "recent" ? "recent" : "priority",
    q: one(sp, "q") ?? "",
    incidents: sp.get("incidents") === "1",
    article: positiveId(sp.get("article")),
    group: one(sp, "group"),
    vindustry: one(sp, "vindustry"),
  };
}

export function parseAllState(sp: URLSearchParams): AllState {
  const s = readState(sp);
  // Aturan 5: satu cerita di bawah urutan prioritas runtuh jadi satu baris, jadi `story` memaksa recent.
  return s.story !== null ? { ...s, sort: "recent" } : s;
}

/** "Reset filters": semua filter URL kembali ke default, `view` dan `article` tidak disebut sehingga
 * tetap (spec 6.2). Satu definisi dipakai rail dan daftar. */
export const RESET_PATCH: Partial<AllState> = {
  period: "7",
  from: null,
  countries: [],
  sector: null,
  sources: [],
  grades: [],
  rubric: null,
  actors: [],
  ttps: [],
  story: null,
  sort: "priority",
  q: "",
  incidents: false,
  group: null,
  vindustry: null,
};

/** Tulis state ke bentuk URL: default (7d, priority, daftar kosong, false) dihilangkan, param di luar
 * state (mis. `view`) dipertahankan. `patch` menimpa state dari `current`; memberi `period` tanpa
 * `from` menghapus `from` (memilih chip periode berarti meninggalkan tanggal manual). */
export function allStateToParams(patch: Partial<AllState>, current: URLSearchParams): URLSearchParams {
  const given = Object.fromEntries(Object.entries(patch).filter(([, v]) => v !== undefined)) as Partial<AllState>;
  const s: AllState = { ...readState(current), ...given };
  if ("period" in given && !("from" in given)) s.from = null;

  const out = new URLSearchParams();
  for (const [k, v] of current) {
    if (!(MANAGED_KEYS as readonly string[]).includes(k)) out.append(k, v);
  }
  if (s.period !== "7") out.set("period", s.period);
  if (s.from) out.set("from", s.from);
  for (const c of s.countries) out.append("country", c);
  if (s.sector) out.set("sector", s.sector);
  for (const v of s.sources) out.append("source", v);
  for (const g of s.grades) out.append("grade", g);
  if (s.rubric) out.set("rubric", s.rubric);
  for (const a of s.actors) out.append("actor", a);
  for (const t of s.ttps) out.append("ttp", t);
  if (s.story !== null) out.set("story", String(s.story));
  if (s.sort === "recent") out.set("sort", "recent");
  if (s.q) out.set("q", s.q);
  if (s.incidents) out.set("incidents", "1");
  if (s.article !== null) out.set("article", String(s.article));
  if (s.group) out.set("group", s.group);
  if (s.vindustry) out.set("vindustry", s.vindustry);
  return out;
}

/** Tampilan turunan (spec 6.1): `view=all`, atau tanpa `view` tetapi ada salah satu param tautan lama
 * (`article`, `rubric`, `actor`, `industry`, `ttp`, `story`) sehingga tautan lama mendarat di sini
 * tanpa redirect. */
export function isAllViewUrl(sp: URLSearchParams): boolean {
  const view = sp.get("view");
  if (view !== null) return view === "all";
  return ["article", "rubric", "actor", "industry", "ttp", "story"].some((k) => values(sp, k).length > 0);
}

/** Query artikel untuk state ini. Hasil non-query: `"empty"` (irisan Watchlist x aktor kosong, tanpa
 * request), `"no-names"` (nama Watchlist/Tech stack kosong), `"pending"` (nama masih dimuat),
 * `"victims"` (Ransomware, bukan artikel). Tanpa `ctx.dateStart` memanggil `periodStart` (membaca
 * jam): hook memberi `dateStart` dari useMemo, jangan panggil tanpa itu di badan render. */
export function allStateToQuery(
  s: AllState,
  ctx: {
    clientCountries: string[];
    watchNames: string[] | undefined;
    techNames: string[] | undefined;
    /** Tanggal mulai yang sudah dihitung pemanggil (di useMemo); tanpa ini fungsi membaca jam sendiri. */
    dateStart?: string;
  },
): ArticleParams | "empty" | "no-names" | "pending" | "victims" {
  const dateStart = ctx.dateStart ?? s.from ?? periodStart(newsroomPeriodInfo(s.period).days ?? 0);
  const base: ArticleParams = {
    posted_on_start: dateStart || undefined,
    country: s.countries.length ? s.countries : undefined,
    industry: s.sector ? [s.sector] : undefined,
    source: s.sources.length ? s.sources : undefined,
    reliability_grade: s.grades.length ? s.grades : undefined,
    threat_actor: s.actors.length ? s.actors : undefined,
    ttp: s.ttps.length ? s.ttps : undefined,
    story_id: s.story ?? undefined,
    search: s.q || undefined,
    confirmed_only: s.incidents || undefined,
    sort: s.sort,
  };
  if (!s.rubric) return compact(base);
  if (s.rubric === "ransomware") return "victims";

  if (s.rubric === "watchlist" && ctx.watchNames === undefined) return "pending";
  if (s.rubric === "techstack" && ctx.techNames === undefined) return "pending";

  // Filter murni dikelola `base`; rubrik hanya menyumbang parameternya sendiri (news_type, nama).
  const r = rubricArticleQuery(
    s.rubric,
    { search: "", dateStart: "", dateEnd: "", country: null, incidentOnly: false },
    ctx,
  );
  if (r === "no-names" || r === "victims") return r;

  // Local memakai negara klien, bukan filter negara (sama seperti rubrik 5b); lainnya mengikuti pilihan negara.
  const merged: ArticleParams = {
    ...base,
    news_type: r.news_type,
    title_keyword: r.title_keyword,
    ...(s.rubric === "local" ? { country: r.country } : {}),
  };
  if (s.rubric === "watchlist") {
    // Aturan 1: Watchlist DAN aktor = irisan tanpa beda huruf besar/kecil; kosong = tanpa request.
    const names = r.threat_actor ?? [];
    if (s.actors.length) {
      const wanted = new Set(s.actors.map((a) => a.toLowerCase()));
      const both = names.filter((n) => wanted.has(n.toLowerCase()));
      if (!both.length) return "empty";
      merged.threat_actor = both;
    } else {
      merged.threat_actor = names;
    }
  }
  return compact(merged);
}

/** Buang kunci undefined supaya perbandingan param dan queryKey stabil. */
function compact(q: ArticleParams): ArticleParams {
  return Object.fromEntries(Object.entries(q).filter(([, v]) => v !== undefined)) as ArticleParams;
}

/** `/newsroom?view=all&...` untuk pemanggil di luar tampilan (Dashboard, Front page). `keepFrom`
 * membawa `period` / `from` dari URL pemanggil; `patch` menimpanya. Pemanggil yang membawa hitungan
 * menambahkan `sort: "recent"` sendiri (aturan 4). */
export function newsroomAllHref(patch: Partial<AllState> & { keepFrom?: URLSearchParams } = {}): string {
  const { keepFrom, ...rest } = patch;
  const start = new URLSearchParams({ view: "all" });
  if (keepFrom) {
    for (const k of ["period", "from"]) {
      const v = keepFrom.get(k);
      if (v) start.set(k, v);
    }
  }
  return `/newsroom?${allStateToParams(rest, start).toString()}`;
}
