import type { AllState } from "@/lib/newsroom/all-state";
import { periodStart } from "@/lib/newsroom/filters";

/**
 * Kontrak URL Newsroom untuk tautan dari tampilan Intelligence (Early Warning,
 * Risk Matrix, MITRE, entitas). Tautan mendarat di tampilan All articles dengan filter
 * gabungan (aktor DAN TTP DAN tanggal), sehingga jumlahnya sama dengan angka di halaman sumber.
 */
export type NewsroomLink = {
  actor?: string;
  industry?: string;
  ttp?: string | string[];
  country?: string;
  /** `YYYY-MM-DD` (tanggal lokal); menang atas `period`. */
  from?: string;
  period?: 1 | 7 | 30;
};

/** Bangun `/newsroom?view=all&...`; nilai di-encode oleh URLSearchParams, `ttp` boleh berulang, nilai kosong dibuang.
 * Selalu `sort=recent` (aturan 4: hitungan tautan sama dengan total API). Tanpa `from`/`period`, tautan lama
 * berarti "semua waktu" sedangkan All articles default 7 hari, jadi `period=all` ditulis eksplisit. */
export function newsroomHref(p: NewsroomLink): string {
  const qs = new URLSearchParams();
  qs.append("view", "all");
  qs.append("sort", "recent");
  const add = (k: string, v: string | undefined) => {
    if (v) qs.append(k, v);
  };
  add("actor", p.actor);
  add("industry", p.industry);
  for (const t of Array.isArray(p.ttp) ? p.ttp : p.ttp ? [p.ttp] : []) add("ttp", t);
  add("country", p.country);
  add("from", p.from);
  if (p.period) qs.append("period", String(p.period));
  else if (!p.from) qs.append("period", "all");
  return `/newsroom?${qs.toString()}`;
}

/** Periode Dashboard (hari, null = semua) -> patch `AllState`. 1/7/30 dan semua waktu punya chip
 * sendiri; 90 hari tidak, jadi jadi tanggal `from`. Membaca jam: panggil di handler atau useMemo,
 * bukan di badan render. */
export function allPeriodPatch(days: number | null): Pick<AllState, "period"> | Pick<AllState, "from"> {
  if (days === null) return { period: "all" };
  if (days === 1 || days === 7 || days === 30) return { period: String(days) as "1" | "7" | "30" };
  return { from: periodStart(days) };
}
