/** Helper murni tanpa import (diuji `node --test`): baca ukuran halaman tersimpan dari teks mentah
 * localStorage. Nilai kosong, bukan angka bulat, atau di luar `options` jatuh ke `fallback`. */
export function parseStoredPageSize(raw: string | null, options: readonly number[], fallback: number): number {
  if (raw === null || !/^\d+$/.test(raw.trim())) return fallback;
  const n = Number(raw);
  return options.includes(n) ? n : fallback;
}

/** Jendela halaman untuk paging di klien: `page` dijepit ke 1..totalPages (daftar kosong tetap 1 halaman), lalu
 * batas slice `[start, end)` untuk `rows.slice(start, end)`. */
export function pageWindow(
  total: number,
  page: number,
  size: number,
): { page: number; totalPages: number; start: number; end: number } {
  const totalPages = Math.max(1, Math.ceil(total / size));
  const p = Math.min(Math.max(1, page), totalPages);
  const start = (p - 1) * size;
  return { page: p, totalPages, start, end: Math.min(start + size, total) };
}
