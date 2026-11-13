import type { components } from "@/lib/api/schema";
import { fmtAgo } from "@/lib/format";

type HealthEntry = components["schemas"]["ScraperHealthEntryOut"];
type ListItem = components["schemas"]["ScraperListItem"];

const DISABLED_BY_LABEL: Record<string, string> = {
  admin: "Turned off by an admin",
  code: "Off by default in code",
  mirror: "Replaced by the CVE mirror",
};

/** Kenapa scraper DISABLED (`disabled_by` + `paused_reason`); null bila keduanya kosong. */
export function disabledReasonText(
  by: string | null | undefined,
  reason: string | null | undefined,
): string | null {
  if (!by && !reason) return null;
  return `${by ? (DISABLED_BY_LABEL[by] ?? by) : ""}${by && reason ? ": " : ""}${reason ?? ""}`;
}

/** Satu kalimat penjelas status untuk panel (spec 6.1). `nowMs` dibaca pemanggil di dalam queryFn. */
export function statusSentence(
  status: string,
  entry: HealthEntry | undefined,
  item: ListItem,
  nowMs: number,
): string {
  if (status === "ok") return "The latest run finished without errors.";
  if (status === "disabled") return disabledReasonText(item.disabled_by, item.paused_reason) ?? "Disabled.";
  if (status === "unknown") return "Health could not be loaded.";
  const parts = [entry?.reason ?? ""];
  if (entry && entry.consecutive_failing > 0) {
    parts.push(` Failing ${entry.consecutive_failing} of the last 3 runs.`);
  }
  parts.push(
    entry?.last_success_at
      ? ` Last success ${fmtAgo(entry.last_success_at, nowMs)}.`
      : " No successful run on record.",
  );
  return parts.join("").trim();
}

/** Hasil run terakhir untuk satu baris: "12 new", "0 items", "fetch error", atau "never". */
export function lastRunOutcome(item: ListItem): string {
  if (!item.last_status) return "never";
  if (item.last_status === "ok") return `${item.last_items_new ?? 0} new`;
  if (item.last_status === "empty") return "0 items";
  return item.last_status.replaceAll("_", " ");
}
