/** Label tick sumbu grafik yang ringkas. Tanpa import. */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-08" -> "8 Nov", "2026-03" -> "Mar 2026"; selain itu (atau tanggal tidak valid) apa adanya.
 * Komponen tanggal dibaca langsung, bukan lewat `new Date(iso)`, supaya tidak bergeser zona UTC. */
export function shortTickLabel(label: string): string {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(label);
  if (day) {
    const y = Number(day[1]);
    const m = Number(day[2]);
    const d = Number(day[3]);
    const dt = new Date(y, m - 1, d);
    if (dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d) {
      return `${d} ${MONTHS[m - 1]}`;
    }
    return label;
  }
  const month = /^(\d{4})-(\d{2})$/.exec(label);
  if (month) {
    const m = Number(month[2]);
    if (m >= 1 && m <= 12) return `${MONTHS[m - 1]} ${month[1]}`;
  }
  return label;
}
