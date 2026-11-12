"use client";

import { RefreshCwIcon, SparklesIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import type { components } from "@/lib/api/schema";
import { formatBuiltAt } from "@/lib/newsletter/format";
import { useCan } from "@/lib/auth/permissions";

type Suggestion = components["schemas"]["NewsletterSuggestionResponse"];

export type SuggestionPhase =
  | { kind: "loading" }
  /** 404: belum ada saran. Keadaan biasa (sebelum hari kerja pertama bulan itu, atau task terlambat). */
  | { kind: "none" }
  | { kind: "error"; message: string }
  | { kind: "ready"; suggestion: Suggestion };

interface Props {
  phase: SuggestionPhase;
  /** Saran ini sudah dipakai (diisi otomatis, "Use suggestion", atau "Merge"). */
  applied: boolean;
  busy: boolean;
  onBuild: () => void;
  onRetry: () => void;
  onUse: () => void;
  onMerge: () => void;
  onRebuild: () => void;
}

function tierCounts(s: Suggestion) {
  const count = (tier: string) => s.items.filter((i) => i.tier === tier).length;
  return { highlights: count("highlight"), cards: count("full"), rows: count("compact") };
}

/** Blok yang terisi di antara Highlights, Indonesia, Asia Pacific, Global (sebuah highlight
 * menghitung untuk Highlights saja, section alaminya tidak dihitung dua kali). */
function filledBlocks(s: Suggestion): number {
  const keys = new Set(s.items.map((i) => (i.tier === "highlight" ? "highlights" : i.section)));
  return keys.size;
}

/**
 * Pita saran di atas halaman (ROADMAP #22, PR 9): memuat, belum ada saran (normal, ada tombol
 * "Build suggestion"), gagal dimuat, saran siap tapi analis sudah punya kerja ("Use suggestion" /
 * "Merge"), atau saran sudah terpasang. Memasang saran ke composer dilakukan pemanggil; di sini
 * hanya tampilan dan tombol.
 */
export function NewsletterSuggestionBar({ phase, applied, busy, onBuild, onRetry, onUse, onMerge, onRebuild }: Props) {
  const can = useCan();
  if (phase.kind === "loading") {
    return <Notice busy title="Loading the suggested content…" className="mb-5" />;
  }

  if (phase.kind === "none") {
    return (
      <Notice
        className="mb-5"
        title="No suggestion yet"
        action={
          can("manage_newsletter") ? (
            <Button type="button" size="sm" onClick={onBuild} disabled={busy}>
              <SparklesIcon aria-hidden /> {busy ? "Building…" : "Build suggestion"}
            </Button>
          ) : undefined
        }
      >
        The monthly job prepares one on the first working day of the month (09:00 WIB). Build it now for the selected
        month: it ranks the month&apos;s articles and, if weekly recaps exist, asks the model for the Executive Summary
        (one call, up to a minute). You can also compose by hand from the queue.
      </Notice>
    );
  }

  if (phase.kind === "error") {
    return (
      <div role="alert" className="mb-5">
        <Notice
          tone="warning"
          title="Could not load the suggestion"
          action={
            <Button type="button" variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          }
        >
          {phase.message}. You can still compose by hand from the queue.
        </Notice>
      </div>
    );
  }

  const s = phase.suggestion;
  const counts = tierCounts(s);
  const summary = `${s.items.length} article${s.items.length === 1 ? "" : "s"}: ${counts.highlights} highlight${counts.highlights === 1 ? "" : "s"}, ${counts.cards} card${counts.cards === 1 ? "" : "s"}, ${counts.rows} Also Noted`;
  const builtAt = formatBuiltAt(s.created_at);
  const rebuild = can("manage_newsletter") ? (
    <Button type="button" variant="ghost" size="sm" onClick={onRebuild} disabled={busy} title="Rebuild the stored suggestion for this month (calls the model again)">
      <RefreshCwIcon aria-hidden className={busy ? "animate-spin" : undefined} /> {busy ? "Rebuilding…" : "Rebuild"}
    </Button>
  ) : null;

  if (!applied) {
    const sections = filledBlocks(s);
    return (
      <Notice
        tone="info"
        className="mb-5"
        title={`✦ Suggestion for ${s.label} ready: ${s.items.length} article${s.items.length === 1 ? "" : "s"} across ${sections} section${sections === 1 ? "" : "s"}`}
        action={
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onMerge}
              disabled={busy}
              title="Adds the suggested articles that are not in your queue, within the limits, and keeps your summary"
            >
              Merge
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={onUse}
              disabled={busy}
              title="Replaces what is placed in the composer and the summary (your queue stays)"
            >
              Use suggestion
            </Button>
            {rebuild}
          </div>
        }
      >
        Built {builtAt} · ranked by severity, APAC relevance and source grade
      </Notice>
    );
  }

  return (
    <Notice className="mb-5" title={`Suggestion for ${s.label}`} action={rebuild}>
      {summary} · built {builtAt}. Review it below: keep, swap, move or remove articles, then preview.
    </Notice>
  );
}
