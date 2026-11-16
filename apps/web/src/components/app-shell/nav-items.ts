/** Tujuan nav masthead (mockup FigCraft). Semua item tampil untuk SEMUA user, sama seperti sidebar
 * lama: `/admin/users` dan aksi tulis `/scrapers` di-guard halaman itu sendiri (lihat
 * `deps.py::require_admin`), bukan disembunyikan dari nav -- port perilaku app lama, link tetap ada
 * di DOM, halamannya yang menolak kalau bukan admin. `/scrapers` sengaja halaman sendiri (keputusan
 * user 2026-09-25), bukan widget di `/dashboard`.
 *
 * Tanpa badge hitungan (keputusan user, redesign FigCraft): mockup menampilkannya, tapi angka itu
 * butuh query tambahan di setiap halaman demi dekorasi. */
export type NavItem = { href: string; label: string; match?: string };

export const NAV_PRIMARY: readonly NavItem[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/newsroom", label: "Newsroom" },
  { href: "/cve", label: "CVE Tracker" },
  { href: "/intelligence", label: "Intelligence" },
  { href: "/exec", label: "Exec" },
  { href: "/xintel", label: "X Intel" },
  { href: "/recap", label: "Recap" },
  { href: "/newsletter", label: "Newsletter" },
];

/** Di balik "More ▾": halaman operasional yang jarang dibuka analis. */
export const NAV_MORE: readonly NavItem[] = [
  { href: "/scrapers", label: "Scrapers" },
  { href: "/data-health", label: "Data health" },
  // Admin punya beberapa sub-route (`/admin/roles`, ...): aktif untuk semua `/admin/*`.
  { href: "/admin/users", label: "Admin", match: "/admin" },
];

/** Aktif bila path sama persis atau di bawah segmen prefiks-nya (`/cve/123`), bukan sekadar
 * `startsWith` mentah supaya `/exec` tidak ikut aktif di route seperti `/executive`. */
export function isActive(pathname: string, item: NavItem): boolean {
  const prefix = item.match ?? item.href;
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}
