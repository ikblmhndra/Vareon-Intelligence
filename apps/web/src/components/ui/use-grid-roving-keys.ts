"use client";

import { useRef, useState, type KeyboardEvent } from "react";

/** Navigasi papan-ketik roving 2-D untuk `HeatGrid`: panah menggeser sel dari sel yang SEDANG FOKUS (bukan
 * dari sel terpilih; berhenti di tepi, tidak melingkar),
 * Home/End = awal/akhir baris, Ctrl+Home/End = sel pertama/terakhir grid, Enter/Spasi memilih sel.
 * Berbeda dari `useRovingKeys` (1-D, seleksi mengikuti fokus): di grid, fokus dan seleksi terpisah supaya
 * panel detail tidak berganti tiap panah ditekan. Sel yang bisa di-Tab = sel yang terakhir fokus; sebelum ada
 * fokus: `active`, atau [0,0]. Pemanggil wajib memasang `onFocusCell(r, c)` pada `onFocus` tiap sel supaya
 * fokus lewat klik/Tab ikut tercatat. */
export function useGridRovingKeys(
  rows: number,
  cols: number,
  active: [number, number] | null,
  onMove: (r: number, c: number) => void,
  onSelect: (r: number, c: number) => void,
) {
  const refs = useRef(new Map<string, HTMLElement>());
  const key = (r: number, c: number) => `${r},${c}`;
  const [focused, setFocused] = useState<[number, number] | null>(null);

  function onKeyDown(e: KeyboardEvent<HTMLElement>) {
    if (rows === 0 || cols === 0) return;
    const [r0, c0] = focused ?? active ?? [0, 0];
    const r = Math.min(r0, rows - 1);
    const c = Math.min(c0, cols - 1);
    let next: [number, number];
    switch (e.key) {
      case "ArrowRight":
        next = [r, Math.min(c + 1, cols - 1)];
        break;
      case "ArrowLeft":
        next = [r, Math.max(c - 1, 0)];
        break;
      case "ArrowDown":
        next = [Math.min(r + 1, rows - 1), c];
        break;
      case "ArrowUp":
        next = [Math.max(r - 1, 0), c];
        break;
      case "Home":
        next = e.ctrlKey ? [0, 0] : [r, 0];
        break;
      case "End":
        next = e.ctrlKey ? [rows - 1, cols - 1] : [r, cols - 1];
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        onSelect(r, c);
        return;
      default:
        return;
    }
    e.preventDefault();
    setFocused(next);
    onMove(next[0], next[1]);
    refs.current.get(key(next[0], next[1]))?.focus();
  }

  // Tanpa fokus maupun `active`, sel pertama yang bisa di-Tab supaya grid tetap terjangkau papan-ketik.
  const tabIndexFor = (r: number, c: number) => {
    const [ar, ac] = focused ?? active ?? [0, 0];
    return ar === r && ac === c ? 0 : -1;
  };

  const setRef = (r: number, c: number) => (el: HTMLElement | null) => {
    if (el) refs.current.set(key(r, c), el);
    else refs.current.delete(key(r, c));
  };

  const onFocusCell = (r: number, c: number) => setFocused([r, c]);

  return { onKeyDown, tabIndexFor, setRef, onFocusCell };
}
