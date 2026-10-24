const SHORT = new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "short" });

/** `posted_on` hanya tanggal (tanpa jam), jadi "N jam lalu" menyesatkan: tampilkan
 * "hari ini", "kemarin", atau tanggal pendek lokal ("22 Okt"). */
export function formatPostedOn(iso: string, now: Date = new Date()): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso.slice(0, 10);
  const posted = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((today.getTime() - posted.getTime()) / 86_400_000);
  if (days === 0) return "hari ini";
  if (days === 1) return "kemarin";
  return SHORT.format(posted);
}
