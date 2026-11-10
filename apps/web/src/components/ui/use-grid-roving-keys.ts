"use client";

import { useRef, type KeyboardEvent } from "react";

/** Navigasi papan-ketik roving 2-D untuk `HeatGrid`: panah menggeser sel (berhenti di tepi, tidak melingkar),
 * Home/End = awal/akhir baris, Ctrl+Home/End = sel pertama/terakhir grid, Enter/Spasi memilih sel.
 * Berbeda dari `useRovingKeys` (1-D, seleksi mengikuti fokus): di grid, fokus dan seleksi terpisah supaya
 * panel detail tidak berganti tiap panah ditekan. Hanya satu sel (`active`, atau [0,0] bila belum ada) yang
 * bisa di-Tab. */
export function useGridRovingKeys(
  rows: number,
  cols: number,
  active: [number, number] | null,
  onMove: (r: number, c: number) => void,
  onSelect: (r: number, c: number) => void,
) {
  const refs = useRef(new Map<string, HTMLElement>());
  const key = (r: number, c: number) => `${r},${c}`;

  function onKeyDown(e: KeyboardEvent<HTMLElement>) {
    if (rows === 0 || cols === 0) return;
    const [r0, c0] = active ?? [0, 0];
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
    onMove(next[0], next[1]);
    refs.current.get(key(next[0], next[1]))?.focus();
  }

  // Tanpa `active`, sel pertama yang bisa di-Tab supaya grid tetap terjangkau papan-ketik.
  const tabIndexFor = (r: number, c: number) => {
    const [ar, ac] = active ?? [0, 0];
    return ar === r && ac === c ? 0 : -1;
  };

  const setRef = (r: number, c: number) => (el: HTMLElement | null) => {
    if (el) refs.current.set(key(r, c), el);
    else refs.current.delete(key(r, c));
  };

  return { onKeyDown, tabIndexFor, setRef };
}
