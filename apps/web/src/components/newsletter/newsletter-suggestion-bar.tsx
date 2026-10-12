"use client";

import type { ReactNode } from "react";
import { CircleAlertIcon, InfoIcon, RefreshCwIcon, SparklesIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { components } from "@/lib/api/schema";
import { formatBuiltAt } from "@/lib/newsletter/format";
import { cn } from "@/lib/utils";

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
  /** Berapa yang sudah dimiliki analis; menentukan teks banner dan apa yang dikatakan tombolnya. */
  queueCount: number;
  placedCount: number;
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

function Bar({ tone, icon, children }: { tone: "info" | "primary" | "error"; icon: "spark" | "info" | "alert"; children: ReactNode }) {
  const Icon = icon === "spark" ? SparklesIcon : icon === "info" ? InfoIcon : CircleAlertIcon;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "mb-5 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border px-4 py-3 text-sm",
        tone === "primary" && "border-primary/40 bg-primary/[0.06]",
        tone === "info" && "border-border bg-surface",
        tone === "error" && "border-destructive/40 bg-destructive/[0.06]",
      )}
    >
      <Icon aria-hidden className={cn("size-4 shrink-0", tone === "error" ? "text-destructive" : "text-primary")} />
      {children}
    </div>
  );
}

/**
 * Pita saran di atas halaman (ROADMAP #22, PR 9): memuat, belum ada saran (normal, ada tombol
 * "Build suggestion"), gagal dimuat, saran siap tapi analis sudah punya kerja ("Use suggestion" /
 * "Merge"), atau saran sudah terpasang. Memasang saran ke composer dilakukan pemanggil; di sini
 * hanya tampilan dan tombol.
 */
export function NewsletterSuggestionBar({ phase, applied, queueCount, placedCount, busy, onBuild, onRetry, onUse, onMerge, onRebuild }: Props) {
  if (phase.kind === "loading") {
    return (
      <Bar tone="info" icon="info">
        <span className="text-muted-foreground">Loading the suggested content…</span>
      </Bar>
    );
  }

  if (phase.kind === "none") {
    return (
      <Bar tone="info" icon="info">
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-foreground">No suggestion yet</div>
          <p className="text-xs text-muted-foreground">
            The monthly job prepares one on the first working day of the month (09:00 WIB). Build it now for the previous
            calendar month: it ranks the month&apos;s articles and, if weekly recaps exist, asks the model for the Executive
            Summary (one call, up to a minute). You can also compose by hand from the queue.
          </p>
        </div>
        <Button type="button" size="sm" onClick={onBuild} disabled={busy}>
          <SparklesIcon aria-hidden /> {busy ? "Building…" : "Build suggestion"}
        </Button>
      </Bar>
    );
  }

  if (phase.kind === "error") {
    return (
      <Bar tone="error" icon="alert">
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-foreground">Could not load the suggestion</div>
          <p className="text-xs text-muted-foreground">{phase.message}. You can still compose by hand from the queue.</p>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      </Bar>
    );
  }

  const s = phase.suggestion;
  const counts = tierCounts(s);
  const summary = `${s.items.length} article${s.items.length === 1 ? "" : "s"}: ${counts.highlights} highlight${counts.highlights === 1 ? "" : "s"}, ${counts.cards} card${counts.cards === 1 ? "" : "s"}, ${counts.rows} Also Noted`;
  const rebuild = (
    <Button type="button" variant="ghost" size="sm" onClick={onRebuild} disabled={busy} title="Rebuild the stored suggestion for this month (calls the model again)">
      <RefreshCwIcon aria-hidden className={busy ? "animate-spin" : undefined} /> {busy ? "Rebuilding…" : "Rebuild"}
    </Button>
  );

  if (!applied) {
    const mine = [queueCount > 0 && `${queueCount} queued`, placedCount > 0 && `${placedCount} placed`].filter(Boolean).join(" and ");
    return (
      <Bar tone="primary" icon="spark">
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-foreground">
            A suggestion for {s.label} is ready{" "}
            <span className="font-normal text-muted-foreground">
              · {summary} · built {formatBuiltAt(s.created_at)}
            </span>
          </div>
          <p className="text-xs text-muted-foreground">
            You already have {mine || "some articles"}, so nothing was filled in. <strong>Use suggestion</strong> replaces what
            is placed in the composer and the summary (your queue stays). <strong>Merge</strong> adds the suggested articles
            that are not in your queue, within the limits, and keeps your summary.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" onClick={onUse} disabled={busy}>
            Use suggestion
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={onMerge} disabled={busy}>
            Merge
          </Button>
          {rebuild}
        </div>
      </Bar>
    );
  }

  return (
    <Bar tone="info" icon="spark">
      <div className="min-w-0 flex-1 text-xs text-muted-foreground">
        <span className="font-semibold text-foreground">Suggestion for {s.label}</span> · {summary} · built{" "}
        {formatBuiltAt(s.created_at)}. Review it below: keep, swap, move or remove articles, then preview.
      </div>
      {rebuild}
    </Bar>
  );
}
