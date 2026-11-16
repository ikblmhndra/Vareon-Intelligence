"use client";

import { useCallback, useEffect, useState } from "react";

import { parseStoredPageSize } from "@/lib/page-size";

/** Ukuran halaman daftar yang diingat per daftar di localStorage (`key`). Dibaca setelah mount supaya
 * render server dan klien sama (awalnya `fallback`); setiap akses storage dibungkus try/catch. */
export function usePageSize(
  key: string,
  options: readonly number[],
  fallback: number,
): [number, (n: number) => void] {
  const [size, setSize] = useState(fallback);

  useEffect(() => {
    try {
      const stored = parseStoredPageSize(window.localStorage.getItem(key), options, fallback);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- baca storage hanya bisa setelah mount
      setSize(stored);
    } catch {
      /* storage diblokir: tetap pakai bawaan */
    }
    // `options` literal konstan milik pemanggil; cukup bergantung pada key dan fallback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, fallback]);

  const update = useCallback(
    (n: number) => {
      setSize(n);
      try {
        window.localStorage.setItem(key, String(n));
      } catch {
        /* abaikan */
      }
    },
    [key],
  );

  return [size, update];
}
