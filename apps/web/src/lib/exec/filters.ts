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

/** Tampilan Exec: Briefing (ringkasan eksekutif) atau Analyst board (papan analis). */
export type ExecView = "briefing" | "board";

export function parseExecView(v: string | null | undefined): ExecView | null {
  return v === "briefing" || v === "board" ? v : null;
}

/** Nama angka utama Exec mengikuti filter yang aktif: `total_incidents` dari API baru berarti
 * insiden kalau "Confirmed only" aktif; dengan "Threat news only" saja isinya berita ancaman
 * (audit UI U7: dulu selalu tertulis "Total Incidents"). */
export function execCountLabel(f: Pick<ExecFilters, "incidentOnly" | "confirmedOnly">): string {
  if (f.confirmedOnly) return "Confirmed Incidents";
  return f.incidentOnly ? "Threat News" : "Articles";
}

/** Padanan huruf kecil untuk kalimat (header halaman). */
export function execCountNoun(f: Pick<ExecFilters, "incidentOnly" | "confirmedOnly">): string {
  if (f.confirmedOnly) return "confirmed incidents";
  return f.incidentOnly ? "threat news articles" : "articles";
}

export const EXEC_DAY_OPTIONS = [7, 30, 90, 180, 365];
export const EXEC_ROLE_PREVIEW_OPTIONS = ["analyst", "soc", "exec", "admin"];

const WATCHLIST_KEY = "cti_exec_idea_watchlist_v1";
const ROLE_PREVIEW_KEY = "exec_role_preview";

/** Port `saveExecWatchlist()`/`restoreExecWatchlist()` (`exec.js`) --
 * client-only, gak ada endpoint backend. `view` ikut disimpan (redesain 3); entri lama tanpa `view` tetap terbaca. */
export function saveExecWatchlist(filters: ExecFilters, view: ExecView): void {
  try {
    localStorage.setItem(
      WATCHLIST_KEY,
      JSON.stringify({ days: filters.days, incidentOnly: filters.incidentOnly, confirmedOnly: filters.confirmedOnly, view }),
    );
  } catch {
    // localStorage bisa gak available (private window dll) -- diemin.
  }
}

export function clearExecWatchlist(): void {
  try {
    localStorage.removeItem(WATCHLIST_KEY);
  } catch {
    // diemin, sama seperti save.
  }
}

/** Hanya kunci yang valid yang ikut dikembalikan, supaya spread ke filter bawaan tidak menimpanya dengan `undefined`. */
export function restoreExecWatchlist(): Partial<Omit<ExecFilters, "rolePreview">> & { view?: ExecView } | null {
  try {
    const raw = localStorage.getItem(WATCHLIST_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw) as { days?: unknown; incidentOnly?: unknown; confirmedOnly?: unknown; view?: unknown };
    const out: Partial<Omit<ExecFilters, "rolePreview">> & { view?: ExecView } = {};
    if (typeof p.days === "number" && EXEC_DAY_OPTIONS.includes(p.days)) out.days = p.days;
    if (typeof p.incidentOnly === "boolean") out.incidentOnly = p.incidentOnly;
    if (typeof p.confirmedOnly === "boolean") out.confirmedOnly = p.confirmedOnly;
    const view = parseExecView(typeof p.view === "string" ? p.view : null);
    if (view) out.view = view;
    return out;
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
