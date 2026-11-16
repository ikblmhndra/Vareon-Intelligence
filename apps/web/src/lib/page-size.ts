/** Helper murni tanpa import (diuji `node --test`): baca ukuran halaman tersimpan dari teks mentah
 * localStorage. Nilai kosong, bukan angka bulat, atau di luar `options` jatuh ke `fallback`. */
export function parseStoredPageSize(raw: string | null, options: readonly number[], fallback: number): number {
  if (raw === null || !/^\d+$/.test(raw.trim())) return fallback;
  const n = Number(raw);
  return options.includes(n) ? n : fallback;
}
