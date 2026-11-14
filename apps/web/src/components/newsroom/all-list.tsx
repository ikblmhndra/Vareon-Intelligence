"use client";

import type { AllState } from "@/lib/newsroom/all-state";

/** Stub Task 5; Task 7 mengisi daftar. Props sudah final. */
export function AllList(_props: {
  state: AllState;
  onChange: (patch: Partial<AllState>) => void;
  selected: number | null;
  onSelect: (id: number) => void;
}) {
  return null;
}
