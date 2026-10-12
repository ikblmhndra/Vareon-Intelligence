import type { RecapScorecardEvent, RecapVerdict } from "@/lib/api/loose-types";

/** Urutan tampil di kontrol override (sama dengan urutan verdict di backend). */
export const VERDICTS: RecapVerdict[] = ["happened", "partly", "not_happened", "unclear"];

export const VERDICT_LABEL: Record<RecapVerdict, string> = {
  happened: "Happened",
  partly: "Partly",
  not_happened: "Not happened",
  unclear: "Unclear",
};

/** Verdict yang berlaku: verdict analis kalau ada, kalau tidak verdict model (aturan yang sama
 * dengan `recap_quality.effective_verdict` di backend, yang dipakai hit rate). */
export function effectiveVerdict(entry: RecapScorecardEvent): RecapVerdict {
  return entry.override?.verdict ?? entry.verdict;
}

/** Alasan penolakan grounding dalam kata-kata pembaca; alasan yang tidak dikenal ditampilkan apa
 * adanya (backend boleh menambah alasan tanpa halaman ini rusak). */
const DROP_REASON: Record<string, string> = {
  not_in_input: "not in the data given to the model",
  malformed: "malformed (not the expected shape)",
  no_article_id: "story without a readable article id",
  unknown_article_id: "article id is not one of the input articles",
};

export function dropReason(reason: string): string {
  return DROP_REASON[reason] ?? reason;
}

/**
 * Teks alasan dari balasan error API. FastAPI mengirim `detail` berupa string (404 "No recap with
 * id 5") atau daftar `{loc, msg}` (422 validasi); `openapi-fetch` sudah membaca body-nya, jadi
 * dibaca dari `error`, bukan dari `response`. Tanpa `detail`, jatuh ke status HTTP.
 */
export function apiErrorMessage(error: unknown, status: number): string {
  const detail = (error as { detail?: unknown } | null | undefined)?.detail;
  let text = "";
  if (typeof detail === "string") {
    text = detail;
  } else if (Array.isArray(detail)) {
    text = detail
      .map((d: unknown) => {
        const item = d as { msg?: unknown; loc?: unknown } | null;
        if (typeof item?.msg !== "string") return JSON.stringify(d);
        const where = Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "";
        return where ? `${where}: ${item.msg}` : item.msg;
      })
      .join("; ");
  } else if (error) {
    text = JSON.stringify(error);
  }
  return text ? text.slice(0, 200) : `HTTP ${status}`;
}

/** URL artikel untuk `href`: hanya http(s). `url` berasal dari artikel hasil scraping (bukan
 * ketikan pengguna), jadi skema lain (`javascript:`, `data:`) tidak dijadikan tautan. */
export function safeHttpUrl(url: string | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:" ? url : undefined;
  } catch {
    return undefined;
  }
}

/** `+12`, `-3` (tanda minus sungguhan U+2212), `0`. */
export function signed(n: number): string {
  if (n === 0) return "0";
  return n > 0 ? `+${n}` : `−${Math.abs(n)}`;
}
