"use client";

export interface ExecFilters {
  days: number;
  incidentOnly: boolean;
  confirmedOnly: boolean;
  rolePreview: string;
}

export function defaultExecFilters(): ExecFilters {
  return { days: 90, incidentOnly: true, confirmedOnly: false, rolePreview: "" };
}

/** Nama angka utama Exec mengikuti filter yang aktif: `total_incidents` dari API baru berarti
 * insiden kalau "Confirmed only" aktif; dengan "Threat news only" saja isinya berita ancaman
 * (audit UI U7: dulu selalu tertulis "Total Incidents"). */
export function execCountLabel(f: Pick<ExecFilters, "incidentOnly" | "confirmedOnly">): string {
  if (f.confirmedOnly) return "Confirmed Incidents";
  return f.incidentOnly ? "Threat News" : "Articles";
}

export const EXEC_DAY_OPTIONS = [7, 30, 90, 180, 365];
export const EXEC_ROLE_PREVIEW_OPTIONS = ["analyst", "soc", "exec", "admin"];

const WATCHLIST_KEY = "cti_exec_idea_watchlist_v1";
const ROLE_PREVIEW_KEY = "exec_role_preview";

/** Port `saveExecWatchlist()`/`restoreExecWatchlist()` (`exec.js`) --
 * client-only, gak ada endpoint backend. */
export function saveExecWatchlist(filters: ExecFilters): void {
  try {
    localStorage.setItem(
      WATCHLIST_KEY,
      JSON.stringify({ days: filters.days, incidentOnly: filters.incidentOnly, confirmedOnly: filters.confirmedOnly }),
    );
  } catch {
    // localStorage bisa gak available (private window dll) -- diemin.
  }
}

export function restoreExecWatchlist(): Partial<ExecFilters> | null {
  try {
    const raw = localStorage.getItem(WATCHLIST_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { days?: number; incidentOnly?: boolean; confirmedOnly?: boolean };
    return { days: parsed.days, incidentOnly: parsed.incidentOnly, confirmedOnly: parsed.confirmedOnly };
  } catch {
    return null;
  }
}

export function getStoredRolePreview(): string {
  try {
    return localStorage.getItem(ROLE_PREVIEW_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setStoredRolePreview(role: string): void {
  try {
    if (role) localStorage.setItem(ROLE_PREVIEW_KEY, role);
    else localStorage.removeItem(ROLE_PREVIEW_KEY);
  } catch {
    // diemin -- port apa adanya legacy, storage kegagalan bukan fatal.
  }
}
