"use client";

import { useRef, type KeyboardEvent } from "react";

/** Navigasi papan-ketik roving untuk tab/radio: panah (kiri/kanan, atas/bawah), Home, End
 * memindahkan fokus sekaligus memilih (seleksi mengikuti fokus). Dipakai `TabPills`, `UnderlineTabs`, dan `SegmentedControl`. */
export function useRovingKeys<T extends string>(
  items: readonly { value: T }[],
  value: T,
  onChange: (value: T) => void,
) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(e: KeyboardEvent<HTMLElement>) {
    const current = items.findIndex((item) => item.value === value);
    let next: number;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (current + 1) % items.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp")
      next = current < 0 ? items.length - 1 : (current - 1 + items.length) % items.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = items.length - 1;
    else return;
    e.preventDefault();
    onChange(items[next].value);
    refs.current[next]?.focus();
  }

  // Tanpa kecocokan `value`, item pertama yang bisa di-Tab supaya grup tetap terjangkau papan-ketik.
  const matched = items.some((item) => item.value === value);
  const tabIndexFor = (i: number) => (matched ? items[i].value === value : i === 0) ? 0 : -1;

  const setRef = (i: number) => (el: HTMLButtonElement | null) => {
    refs.current[i] = el;
  };

  return { onKeyDown, setRef, tabIndexFor };
}
