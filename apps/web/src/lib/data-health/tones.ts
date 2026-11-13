import type { components } from "@/lib/api/schema";
import type { AttackDomainStatus } from "@/lib/api/loose-types";

type S = components["schemas"];

export type Tone = "ok" | "warn" | "bad" | "unknown";

export const TONE_LABEL: Record<Tone, string> = { ok: "OK", warn: "WATCH", bad: "ACTION", unknown: "UNKNOWN" };

/** Nada `StatTile` untuk tiap nada halaman. */
export const TONE_STYLE: Record<Tone, "success" | "warning" | "destructive" | "neutral"> = {
  ok: "success",
  warn: "warning",
  bad: "destructive",
  unknown: "neutral",
};

const RANK: Record<Tone, number> = { bad: 3, warn: 2, unknown: 1, ok: 0 };

/** Roll-up: bad > warn > unknown > ok; kosong = unknown. */
export function worstTone(tones: readonly Tone[]): Tone {
  return tones.reduce<Tone | null>((w, t) => (w === null || RANK[t] > RANK[w] ? t : w), null) ?? "unknown";
}

/** "42%"; penyebut 0 dicetak "0%" (bukan NaN). */
export function pct(part: number, whole: number): string {
  return whole > 0 ? `${Math.round((part / whole) * 100)}%` : "0%";
}

const HOUR_MS = 3_600_000;

/** Umur dalam jam terhadap `nowMs` (dibaca pemanggil di dalam queryFn); `null` untuk kosong/tidak valid. */
export function ageHours(iso: string | null | undefined, nowMs: number): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : (nowMs - ms) / HOUR_MS;
}

export function byAge(iso: string | null | undefined, warnH: number, badH: number, nowMs: number): Tone {
  const h = ageHours(iso, nowMs);
  if (h === null) return "unknown";
  return h > badH ? "bad" : h > warnH ? "warn" : "ok";
}

export function pipelineTone(scrapers: S["ScraperHealthSummary"]): Tone {
  return scrapers.scheduler.state !== "ok" ? "bad" : scrapers.problems.length ? "warn" : "ok";
}

export function queueTone(queues: S["QueueHealthOut"]): Tone {
  const { enrich_depth: depth, enrich_max_depth: max } = queues;
  if (depth === null) return "unknown";
  return depth >= max ? "bad" : depth >= max / 2 ? "warn" : "ok";
}

/** Job antre baru dianggap WATCH bila yang tertua sudah menunggu lebih dari ini. */
const PENDING_WATCH_MS = 15 * 60_000;

export function llmJobsTone(llm: S["LlmHealthOut"], nowMs: number): Tone {
  const q = llm.queue;
  if (llm.status === "failing" || q.breaker === "open") return "bad";
  const oldest = q.oldest_pending_at ? Date.parse(q.oldest_pending_at) : NaN;
  const pending = q.pending_classify + q.pending_ttp;
  const stale = pending > 0 && (!Number.isFinite(oldest) || nowMs - oldest > PENDING_WATCH_MS);
  if (q.breaker === "half_open" || q.failed > 0 || stale) return "warn";
  return llm.status === "unknown" ? "unknown" : "ok";
}

export function relevanceTone(rel: S["RelevanceHealthOut"]): Tone {
  return rel.mode === "off" || rel.gate_state === null ? "unknown" : "ok";
}

export function failedJobsTone(e: S["EnrichmentHealthOut"]): Tone {
  if ((e.processed_7d > 0 && e.failed_7d / e.processed_7d >= 0.1) || e.failed_24h >= 5) return "bad";
  return e.pending_replay > 0 ? "warn" : "ok";
}

export function cveIngestTone(ci: S["CveIngestHealthOut"]): Tone {
  return ci.status === "ok" ? "ok" : ci.status === "amber" ? "warn" : ci.status === "red" ? "bad" : "unknown";
}

export function sigmaTone(s: S["SigmaHealthOut"]): Tone {
  return s.status === "ok" ? "ok" : s.status === "amber" ? "warn" : "bad";
}

/** ATT&CK: domain `error` = bad; sinkron terakhir lebih dari 30 hari (atau tanpa sinkron) = warn;
 * daftar kosong, belum dimuat, atau gagal dimuat = unknown. */
export function attackTone(domains: AttackDomainStatus[] | undefined, failed: boolean, nowMs: number): Tone {
  if (failed || !domains || domains.length === 0) return "unknown";
  if (domains.some((x) => x.status === "error")) return "bad";
  if (domains.some((x) => (ageHours(x.last_sync, nowMs) ?? Infinity) > 30 * 24)) return "warn";
  return "ok";
}

export type FreshnessRow = {
  key: "article" | "tweet" | "ioc" | "cve" | "attack";
  label: string;
  caption: string;
  tileSub: string;
  at: string | null;
  state: "ready" | "loading" | "failed";
  tone: Tone;
};

/** Lima baris kesegaran sesuai urutan kartu; query samping yang memuat/gagal memberi tone unknown. */
export function freshnessRows(
  input: {
    sources: S["SourceFreshnessOut"];
    cveCheckedAt: string | null | undefined;
    cveState: FreshnessRow["state"];
    attack: AttackDomainStatus[] | undefined;
    attackState: FreshnessRow["state"];
  },
  nowMs: number,
): FreshnessRow[] {
  const { sources, cveCheckedAt, cveState, attack, attackState } = input;
  const attackAt =
    (attack ?? [])
      .map((x) => x.last_sync)
      .filter((x): x is string => !!x && !Number.isNaN(Date.parse(x)))
      .sort()
      .at(-1) ?? null;
  const cveAt = cveCheckedAt ?? null;
  return [
    {
      key: "article",
      label: "Newest article",
      caption: "watch after 6 h · action after 24 h",
      tileSub: "since the newest article",
      at: sources.articles_newest_at,
      state: "ready",
      tone: byAge(sources.articles_newest_at, 6, 24, nowMs),
    },
    {
      key: "tweet",
      label: "Newest tweet (X Intel)",
      caption: "watch after 24 h · action after 72 h",
      tileSub: "since the newest X Intel tweet",
      at: sources.tweets_newest_at,
      state: "ready",
      tone: byAge(sources.tweets_newest_at, 24, 72, nowMs),
    },
    {
      key: "ioc",
      label: "Newest IOC",
      caption: "watch after 24 h · action after 72 h",
      tileSub: "since the newest IOC",
      at: sources.iocs_newest_at,
      state: "ready",
      tone: byAge(sources.iocs_newest_at, 24, 72, nowMs),
    },
    {
      key: "cve",
      label: "CVE check",
      caption: "watch after 6 h · action after 24 h",
      tileSub: "since the last CVE check",
      at: cveAt,
      state: cveState,
      tone: cveState === "ready" ? byAge(cveAt, 6, 24, nowMs) : "unknown",
    },
    {
      key: "attack",
      label: "ATT&CK sync",
      caption: "watch when a domain is over 30 days old · action when a sync failed",
      tileSub: "since the last ATT&CK sync",
      at: attackAt,
      state: attackState,
      tone: attackState === "ready" ? attackTone(attack, false, nowMs) : "unknown",
    },
  ];
}

/** Baris terburuk menurut roll-up; seri dan semua-OK jatuh ke yang pertama di urutan kartu. */
export function worstFreshness(rows: readonly FreshnessRow[]): FreshnessRow {
  return rows.reduce((w, r) => (RANK[r.tone] > RANK[w.tone] ? r : w));
}

/** Status halaman dari nada delapan area: ACTION bila ada bad, lalu WATCH, UNKNOWN hanya bila semuanya unknown. */
export function pageStatus(areas: readonly Tone[]): { tone: Tone; bad: number; warn: number; unknown: number } {
  const count = (t: Tone) => areas.filter((a) => a === t).length;
  const bad = count("bad");
  const warn = count("warn");
  const unknown = count("unknown");
  const tone: Tone = bad ? "bad" : warn ? "warn" : unknown === areas.length ? "unknown" : "ok";
  return { tone, bad, warn, unknown };
}
