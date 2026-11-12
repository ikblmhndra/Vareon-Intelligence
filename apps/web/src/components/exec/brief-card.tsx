"use client";

import { useMemo } from "react";
import Markdown from "react-markdown";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { useCan } from "@/lib/auth/permissions";
import { briefFiltersLabel, parseBrief } from "@/lib/exec/brief";
import type { ExecFilters } from "@/lib/exec/filters";
import { useBrief, useBriefDates } from "@/lib/exec/use-brief";
import { fmtDateTime, fmtShortDate, fmtTime, parseLocalDate } from "@/lib/format";

const FALLBACK_CHARS = 600;
const SHOW_FINDINGS = 3;

/** Tanggal brief = tanggal kalender Jakarta; selisih sehari dihitung di kalender lokal tanpa konversi zona. */
function dateLabel(date: string, today: string): string {
  if (date === today) return "Today";
  const y = parseLocalDate(today);
  y.setDate(y.getDate() - 1);
  const iso = `${y.getFullYear()}-${String(y.getMonth() + 1).padStart(2, "0")}-${String(y.getDate()).padStart(2, "0")}`;
  return date === iso ? "Yesterday" : fmtShortDate(date);
}

interface BriefCardProps {
  /** Filter halaman: hanya dipakai untuk tombol Generate di keadaan kosong (diteruskan induk lewat `onGenerate`). */
  filters: ExecFilters;
  selectedDate: string | null;
  onSelectDate: (date: string | null) => void;
  onOpenDialog: () => void;
  onGenerate: () => void;
  generateDisabled?: boolean;
  generating: boolean;
}

/** Kartu brief di baris utama Briefing (6.3). Menarik brief sendiri lewat react-query (key sama dengan
 * halaman, jadi satu request). `filters` tidak dibaca di sini; induk yang memakainya saat `onGenerate`. */
export function BriefCard({ selectedDate, onSelectDate, onOpenDialog, onGenerate, generateDisabled, generating }: BriefCardProps) {
  const can = useCan();
  const q = useBrief(selectedDate);
  const datesQ = useBriefDates();
  const read = q.data;
  const brief = read?.brief ?? null;
  const today = read?.today ?? datesQ.data?.today ?? null;
  const parsed = useMemo(() => (brief ? parseBrief(brief.markdown) : null), [brief]);

  const pickerValue = selectedDate ?? brief?.brief_date ?? today;
  const pickerItems = useMemo(() => {
    const set = new Set(datesQ.data?.dates ?? []);
    if (pickerValue) set.add(pickerValue);
    const out: Record<string, string> = {};
    for (const d of [...set].sort().reverse()) out[d] = today ? dateLabel(d, today) : fmtShortDate(d);
    return out;
  }, [datesQ.data, pickerValue, today]);

  const picker = pickerValue && (
    <Select items={pickerItems} value={pickerValue} onValueChange={(v) => v && onSelectDate(v)}>
      <SelectTrigger size="sm" aria-label="Brief date" className="w-32 text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {Object.entries(pickerItems).map(([value, label]) => (
          <SelectItem key={value} value={value}>
            {label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );

  let body: React.ReactNode;
  if (q.isPending) {
    body = (
      <div className="space-y-3" aria-hidden="true">
        <Skeleton className="h-6 w-3/4" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-11/12" />
        <Skeleton className="h-3 w-4/5" />
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-3/5" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    );
  } else if (q.isError) {
    body = (
      <StatePanel
        variant="error"
        title="Could not load the brief"
        action={
          <Button size="sm" variant="outline" onClick={() => void q.refetch()}>
            Retry
          </Button>
        }
      />
    );
  } else if (!brief) {
    const isToday = today !== null && (selectedDate === null || selectedDate === today);
    body = (
      <StatePanel
        variant="empty"
        title="No brief for this date yet"
        description={
          can("manage_intel")
            ? isToday
              ? undefined
              : "Briefs can only be generated for today."
            : "Briefs are generated every morning from 06:00 Jakarta time, retried hourly until 18:00."
        }
        action={
          can("manage_intel") && isToday ? (
            <Button size="sm" loading={generating} disabled={generateDisabled} onClick={onGenerate}>
              Generate brief
            </Button>
          ) : undefined
        }
      />
    );
  } else {
    const isToday = brief.brief_date === today;
    const findings = parsed?.findings ?? [];
    body = (
      <div className="space-y-3">
        {!selectedDate && !isToday && (
          <Notice tone="info" title={`Today's brief is not ready yet. Showing ${fmtShortDate(brief.brief_date)}.`} />
        )}
        {generating && <Notice busy title="Generating a new brief. This can take up to a minute." />}
        <div className="space-y-1">
          <p className="text-2xs text-muted-foreground">
            AI brief · generated by {brief.generated_by} ·{" "}
            {isToday ? fmtTime(brief.generated_at) : fmtDateTime(brief.generated_at)}
          </p>
          {!brief.is_default_filters && (
            <p className="text-2xs text-muted-foreground">Filters: {briefFiltersLabel(brief.filters).toLowerCase()}</p>
          )}
          <p className="text-2xs text-muted-foreground">Platform-wide brief, the same for every client.</p>
        </div>

        {parsed ? (
          <>
            <h3 className="font-heading text-lg leading-snug font-semibold text-foreground">{parsed.headline}</h3>
            {parsed.paragraph && (
              <div className="prose prose-sm max-w-none text-xs leading-relaxed">
                <Markdown>{parsed.paragraph}</Markdown>
              </div>
            )}
            {findings.length > 0 && (
              <ol className="space-y-2">
                {findings.slice(0, SHOW_FINDINGS).map((f, i) => (
                  <li key={i} className="flex gap-2 text-xs">
                    <span className="font-code text-muted-foreground">{i + 1}.</span>
                    <span className="min-w-0">
                      <span className="font-semibold text-foreground">{f.title}</span>
                      {f.detail && <span className="block text-muted-foreground">{f.detail}</span>}
                    </span>
                  </li>
                ))}
              </ol>
            )}
            {findings.length > SHOW_FINDINGS && (
              <p className="text-2xs text-muted-foreground">+{findings.length - SHOW_FINDINGS} more in the full brief</p>
            )}
            {parsed.otherSections.length > 0 && (
              <p className="text-2xs text-muted-foreground">Also in the brief: {parsed.otherSections.join(" · ")}</p>
            )}
          </>
        ) : (
          // Balasan tanpa struktur yang dikenali: tampilkan Markdown apa adanya (potong ~600 karakter, memudar).
          <div className="relative max-h-48 overflow-hidden">
            <div className="prose prose-sm max-w-none text-xs leading-relaxed">
              <Markdown>{brief.markdown.slice(0, FALLBACK_CHARS)}</Markdown>
            </div>
            {brief.markdown.length > FALLBACK_CHARS && (
              <div aria-hidden="true" className="absolute inset-x-0 bottom-0 h-12 bg-linear-to-t from-surface to-transparent" />
            )}
          </div>
        )}
        <Button variant="link" size="sm" className="h-auto px-0 text-primary-text" onClick={onOpenDialog}>
          Read full brief →
        </Button>
      </div>
    );
  }

  return (
    <section aria-label="Executive summary" className="rounded-lg bg-surface p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-2xs font-semibold tracking-wider text-muted-foreground uppercase">Executive summary</h2>
        {picker}
      </div>
      {body}
    </section>
  );
}
