import { useSyncExternalStore } from "react";

/**
 * Status sesi di sisi browser, modul-level (bukan state React) supaya `lib/api/client.ts`
 * (non-React) dan UI membaca satu sumber. `expired` = 401 sudah terlihat: tidak ada request lagi ke
 * API dan dialog "sesi berakhir" tampil sekali. `signing-out` = logout disengaja: 401 yang masuk
 * saat itu tidak boleh membuka dialog.
 */
export type SessionState = "active" | "expired" | "signing-out";

let state: SessionState = "active";
const listeners = new Set<() => void>();

function set(next: SessionState): void {
  if (state === next) return;
  state = next;
  listeners.forEach((l) => l());
}

export function getSessionState(): SessionState {
  return state;
}

/** Hanya `active` -> `expired`; dari state lain tidak melakukan apa pun (dialog tidak terbuka dua kali). */
export function markSessionExpired(): void {
  if (state === "active") set("expired");
}

export function markSigningOut(): void {
  set("signing-out");
}

export function resetSessionExpired(): void {
  set("active");
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useSessionState(): SessionState {
  return useSyncExternalStore(subscribe, getSessionState, () => "active");
}
