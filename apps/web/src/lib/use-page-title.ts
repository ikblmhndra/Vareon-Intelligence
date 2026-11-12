import { useEffect } from "react";

import { PLATFORM_NAME } from "@/lib/brand";

/**
 * Judul tab browser untuk halaman yang judulnya baru diketahui di klien (mis. "Weekly recap 2026-W45").
 * Template layout hanya dipakai di render server, jadi hook memasang sufiks yang sama sendiri.
 * Judul lama disimpan dan dipulihkan saat unmount HANYA kalau judul itu masih milik kita: halaman
 * tujuan mungkin sudah memasang judulnya sendiri lebih dulu (pola `entity-view.tsx`). `null` = tidak
 * melakukan apa-apa (data belum dimuat).
 */
export function usePageTitle(title: string | null) {
  useEffect(() => {
    if (title == null) return;
    const previous = document.title;
    const mine = `${title} · ${PLATFORM_NAME}`;
    document.title = mine;
    return () => {
      if (document.title === mine) document.title = previous;
    };
  }, [title]);
}
