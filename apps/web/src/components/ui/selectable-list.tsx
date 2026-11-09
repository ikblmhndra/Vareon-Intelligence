"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { useRovingKeys } from "./use-roving-keys";

interface SelectableListProps<T extends string, I extends { value: T }> {
  items: readonly I[];
  value: T | null;
  onChange: (value: T) => void;
  "aria-label": string;
  renderItem: (item: I, selected: boolean) => ReactNode;
  className?: string;
}

/** Daftar pilih-satu (`listbox`): panah/Home/End memindahkan fokus sekaligus memilih (roving tabindex).
 * Item terpilih = `bg-surface` + garis tinta 2 px di kiri. */
export function SelectableList<T extends string, I extends { value: T }>({
  items,
  value,
  onChange,
  "aria-label": ariaLabel,
  renderItem,
  className,
}: SelectableListProps<T, I>) {
  // Hook mengetikkan `value` sebagai T; saat tak ada pilihan, string kosong tak cocok item mana pun.
  const { onKeyDown, setRef, tabIndexFor } = useRovingKeys(items, (value ?? "") as T, onChange);

  return (
    <div
      role="listbox"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={cn("flex flex-col gap-1", className)}
    >
      {items.map((item, i) => {
        const selected = item.value === value;
        return (
          <SelectableListItem
            key={item.value}
            selected={selected}
            tabIndex={tabIndexFor(i)}
            buttonRef={setRef(i)}
            onSelect={() => onChange(item.value)}
          >
            {renderItem(item, selected)}
          </SelectableListItem>
        );
      })}
    </div>
  );
}

function SelectableListItem({
  selected,
  tabIndex,
  buttonRef,
  onSelect,
  children,
}: {
  selected: boolean;
  tabIndex: number;
  buttonRef: (el: HTMLButtonElement | null) => void;
  onSelect: () => void;
  children: ReactNode;
}) {
  return (
    <button
      ref={buttonRef}
      type="button"
      role="option"
      aria-selected={selected}
      aria-current={selected ? "true" : undefined}
      tabIndex={tabIndex}
      onClick={onSelect}
      className={cn(
        "w-full rounded-[10px] px-3 py-2.5 text-left outline-none transition-colors hover:bg-surface focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        selected && "bg-surface shadow-[inset_2px_0_0_var(--foreground)]",
      )}
    >
      {children}
    </button>
  );
}
