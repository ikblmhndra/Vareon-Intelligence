/**
 * Kontrak URL Newsroom untuk tautan dari tampilan Intelligence (Early Warning,
 * Risk Matrix, MITRE, entitas). Halaman Newsroom membaca parameter ini sekali saat
 * dimuat dan membuka sheet artikel dengan filter gabungan (aktor DAN TTP DAN tanggal),
 * sehingga jumlahnya sama dengan angka di halaman sumber.
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

/** Bangun `/newsroom?...`; nilai di-encode oleh URLSearchParams, `ttp` boleh berulang, nilai kosong dibuang. */
export function newsroomHref(p: NewsroomLink): string {
  const qs = new URLSearchParams();
  const add = (k: string, v: string | undefined) => {
    if (v) qs.append(k, v);
  };
  add("actor", p.actor);
  add("industry", p.industry);
  for (const t of Array.isArray(p.ttp) ? p.ttp : p.ttp ? [p.ttp] : []) add("ttp", t);
  add("country", p.country);
  add("from", p.from);
  if (p.period) qs.append("period", String(p.period));
  const s = qs.toString();
  return s ? `/newsroom?${s}` : "/newsroom";
}
