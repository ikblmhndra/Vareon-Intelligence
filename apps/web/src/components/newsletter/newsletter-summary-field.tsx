"use client";

import { CircleAlertIcon, InfoIcon, RefreshCwIcon, TriangleAlertIcon } from "lucide-react";
import { useRef, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { NewsletterSummaryMeta } from "@/lib/api/loose-types";
import {
  CVE_MARKER,
  countCveMarkers,
  coveredLabel,
  nextMarkerIndex,
  summaryStatus,
  uncoveredLabels,
  weekLabels,
  type SummaryStatus,
} from "@/lib/newsletter/summary";
import { cn } from "@/lib/utils";

interface Props {
  /** Isi field = `custom_intro` (HTML), yang dirender template sebagai blok Executive Summary. */
  value: string;
  onChange: (value: string) => void;
  /** Saran yang dimuat; null selagi memuat, kalau belum ada, atau kalau gagal dimuat. */
  suggestion: { summary_text: string; summary_meta: Record<string, unknown> } | null;
  /** Isi field yang akan dihasilkan `summary_text` saran; kosong kalau saran tanpa ringkasan. */
  suggestedIntro: string;
  rebuilding: boolean;
  onUseSuggested: () => void;
  onRebuild: () => void;
}

type Tone = "info" | "warning" | "error";

const TONE_CLASS: Record<Tone, string> = {
  info: "border-info/40 bg-info/[0.06] text-foreground",
  warning: "border-warning/40 bg-warning/[0.06] text-foreground",
  error: "border-destructive/40 bg-destructive/[0.06] text-foreground",
};
const TONE_ICON_CLASS: Record<Tone, string> = { info: "text-info", warning: "text-warning", error: "text-destructive" };

function Notice({ tone, children, action }: { tone: Tone; children: ReactNode; action?: ReactNode }) {
  const Icon = tone === "info" ? InfoIcon : tone === "warning" ? TriangleAlertIcon : CircleAlertIcon;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn("flex flex-wrap items-start gap-2 rounded-lg border px-3 py-2 text-xs", TONE_CLASS[tone])}
    >
      <Icon aria-hidden className={cn("mt-0.5 size-3.5 shrink-0", TONE_ICON_CLASS[tone])} />
      <div className="min-w-0 flex-1 space-y-0.5">{children}</div>
      {action}
    </div>
  );
}

/** Pesan satu-satunya yang menjelaskan KENAPA field kosong: empat sebab yang berbeda dan tiap
 * sebabnya punya jalan keluar yang berbeda, jadi tidak digabung jadi satu "no summary". */
function statusNotice(status: SummaryStatus, rebuild: ReactNode): ReactNode {
  switch (status.kind) {
    case "llm_error":
      return (
        <Notice tone="error" action={rebuild}>
          <p className="font-semibold">The language model was unavailable, so no summary was written.</p>
          <p className="text-muted-foreground">
            Error: <span className="font-mono">{status.error}</span>. The suggested articles are not affected. Rebuild
            when the model is back, or write the summary by hand below.
          </p>
        </Notice>
      );
    case "parse_failed":
      return (
        <Notice tone="warning" action={rebuild}>
          <p className="font-semibold">The model answered, but without a usable paragraph.</p>
          <p className="text-muted-foreground">Rebuild to try again, or write the summary by hand below.</p>
        </Notice>
      );
    case "no_recaps":
      return (
        <Notice tone="info" action={rebuild}>
          <p className="font-semibold">There are no weekly recaps for this month, so there was nothing to condense.</p>
          <p className="text-muted-foreground">
            Generate the weekly recaps on the Recap page and rebuild, or write the summary by hand below.
          </p>
        </Notice>
      );
    case "empty":
      return (
        <Notice tone="info" action={rebuild}>
          <p className="font-semibold">The suggestion has no summary.</p>
          <p className="text-muted-foreground">Rebuild the suggestion, or write the summary by hand below.</p>
        </Notice>
      );
    case "ok":
      return null;
  }
}

/**
 * Blok Executive Summary composer (ROADMAP #22, PR 9): field `custom_intro` yang diisi dulu dari
 * paragraf saran, dengan pekan yang diliputnya, peringatan ekor bulan yang tidak terliput, dan
 * penjelasan kalau kosong. Analis menyunting di sini; hasil editan hidup di state browser, bukan di
 * saran tersimpan (yang tidak berubah sampai di-rebuild).
 */
export function NewsletterSummaryField({ value, onChange, suggestion, suggestedIntro, rebuilding, onUseSuggested, onRebuild }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const meta = (suggestion?.summary_meta ?? {}) as NewsletterSummaryMeta;
  const status = suggestion ? summaryStatus(suggestion.summary_text, meta) : null;
  const weeks = weekLabels(meta);
  const gaps = uncoveredLabels(meta);
  const covered = coveredLabel(meta);
  const dropped = meta.dropped ?? [];
  const markers = countCveMarkers(value);
  const singleGap = gaps.length === 1 && !gaps[0].includes(" - ");
  const canUseSuggested = suggestedIntro !== "" && value.trim() !== suggestedIntro;

  const rebuildButton = (
    <Button type="button" variant="outline" size="xs" onClick={onRebuild} disabled={rebuilding}>
      <RefreshCwIcon aria-hidden className={rebuilding ? "animate-spin" : undefined} />
      {rebuilding ? "Rebuilding…" : "Rebuild"}
    </Button>
  );

  /** Pilih penanda berikutnya di textarea supaya analis tidak mencarinya di teks panjang. */
  function jumpToMarker() {
    const el = ref.current;
    if (!el) return;
    const at = nextMarkerIndex(value, el.selectionEnd ?? 0);
    if (at === -1) return;
    el.focus();
    el.setSelectionRange(at, at + CVE_MARKER.length);
  }

  return (
    <section aria-label="Executive Summary" className="mb-5 space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <Label htmlFor="exec-summary" className="text-sm font-semibold text-foreground">
          Executive Summary
        </Label>
        <span className="text-xs text-muted-foreground">Indonesian paragraph, HTML allowed</span>
      </div>

      {suggestion && status && statusNotice(status, rebuildButton)}

      {suggestion && weeks.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Based on {weeks.length} weekly recap{weeks.length === 1 ? "" : "s"}
          {covered ? ` covering ${covered}` : ""}:{" "}
          <span className="font-mono">{weeks.join(" · ")}</span>
        </p>
      )}

      {/* Tanpa recap sama sekali seluruh bulan "tidak terliput"; itu sudah dijelaskan pesan di atas. */}
      {gaps.length > 0 && status?.kind !== "no_recaps" && (
        <Notice tone="warning">
          <p className="font-semibold">The summary does not cover {gaps.join(", ")}.</p>
          <p className="text-muted-foreground">
            No weekly recap exists for {singleGap ? "that day" : "those days"} yet: the week is still running (the usual
            case at the end of a month) or its recap was not generated. Articles from {singleGap ? "that day are" : "those days are"}{" "}
            still ranked in the suggestion; mention anything important by hand.
          </p>
        </Notice>
      )}

      {dropped.length > 0 && (
        <details className="rounded-lg border border-border px-3 py-1.5 text-xs">
          <summary className="cursor-pointer text-muted-foreground">
            The grounding check changed {dropped.length} item{dropped.length === 1 ? "" : "s"} that the source recaps do not support
          </summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 font-mono text-muted-foreground">
            {dropped.map((d, i) => (
              <li key={`${d.field}-${d.value}-${i}`}>
                {d.field}: {d.value} ({d.reason})
              </li>
            ))}
          </ul>
        </details>
      )}

      {markers > 0 && (
        <Notice
          tone="error"
          action={
            <Button type="button" variant="outline" size="xs" onClick={jumpToMarker}>
              Find next
            </Button>
          }
        >
          <p className="font-semibold">
            {markers} unverified CVE marker{markers === 1 ? "" : "s"} in the summary.
          </p>
          <p className="text-muted-foreground">
            The model named a CVE that the source recaps do not contain. Replace{" "}
            <span className="font-mono">{CVE_MARKER}</span> with the right id or delete the sentence before sending.
          </p>
        </Notice>
      )}

      <Textarea
        id="exec-summary"
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="<p>Ringkasan eksekutif bulan ini…</p>"
        className="h-36 resize-y font-mono text-xs leading-relaxed"
      />

      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" size="xs" onClick={onUseSuggested} disabled={!canUseSuggested}>
          Use suggested summary
        </Button>
        {status?.kind === "ok" ? rebuildButton : null}
        <span className="text-xs text-muted-foreground">Edits live in this page only; the stored suggestion is not changed.</span>
      </div>
    </section>
  );
}
