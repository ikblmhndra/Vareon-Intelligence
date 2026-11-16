"use client";

import { useEffect, useRef } from "react";
import { ChevronLeftIcon } from "lucide-react";

import type { RecapDoc, RecapKind, RecapListItem } from "@/lib/api/loose-types";
import { fmtShortDate } from "@/lib/format";
import { formatRange, isoWeek, isoWeekYear, previousPeriod, weekHeading } from "@/lib/recap/period";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

interface RecapPageHeaderProps {
  /** Recap yang tampil; null saat memuat atau kosong (judul jatuh ke "Recap"). */
  doc: RecapDoc | null;
  /** Periode yang dipilih (dari URL atau dari recap terbaru); kosong selama `/latest` belum menjawab. */
  kind: RecapKind | null;
  date: string | null;
  list: RecapListItem[];
  canGenerate: boolean;
  onSelect: (kind: RecapKind, date: string) => void;
  onPrevious: () => void;
  onRegenerate: () => void;
  generating: boolean;
}

const histKey = (kind: RecapKind, date: string) => `${kind}:${date}`;

function historyLabel(it: RecapListItem): string {
  const n = `${it.counts?.articles ?? 0} articles`;
  return it.kind === "weekly"
    ? `${formatRange(it.period_start, it.period_end)} · week · ${n}`
    : `${it.date} · day · ${n}`;
}

/** Header Recap: kicker/judul dari recap yang tampil, lalu aksi (sebelumnya, history, ekspor, buat ulang). */
export function RecapPageHeader(props: RecapPageHeaderProps) {
  const { doc, kind, date, list, canGenerate, onSelect, onPrevious, onRegenerate, generating } = props;
  const restoreRef = useRef<(() => void) | null>(null);
  // Bila halaman ditinggalkan di tengah dialog cetak, tema dan judul tetap dipulihkan.
  useEffect(() => () => restoreRef.current?.(), []);

  let kicker: string | undefined;
  let title = "Recap";
  let description: string | undefined;
  if (doc) {
    if (doc.kind === "weekly") {
      kicker = "WEEKLY RECAP";
      title = weekHeading(doc.period_start, doc.period_end);
      description = "AI-written recap of the week, grounded in the articles and posts it cites";
    } else {
      kicker = "DAILY RECAP";
      title = `Recap for ${fmtShortDate(doc.date, { withYear: true })}`;
      description = "AI-written recap of the day, grounded in the articles and posts it cites";
    }
  }

  const prev = kind && date ? previousPeriod(kind, date) : null;
  const prevLabel =
    kind && prev ? (kind === "weekly" ? `Week ${isoWeek(prev)}` : fmtShortDate(prev, { withYear: true })) : "";

  const items: Record<string, string> = {};
  for (const it of list) items[histKey(it.kind, it.date)] = historyLabel(it);
  const current = kind && date ? histKey(kind, date) : null;

  function exportPdf() {
    if (!kind || !date || restoreRef.current) return; // klik kedua sebelum afterprint
    const root = document.documentElement;
    const previousTitle = document.title;
    const wasDark = root.classList.contains("dark");
    document.title =
      kind === "weekly"
        ? `Weekly recap ${isoWeekYear(date)}-W${String(isoWeek(date)).padStart(2, "0")}`
        : `Daily recap ${date}`;
    // Cetak selalu terang di kertas putih; gelapnya dikembalikan sesudah dialog cetak ditutup.
    root.classList.remove("dark");
    const restore = () => {
      window.removeEventListener("afterprint", restore);
      document.title = previousTitle;
      if (wasDark) root.classList.add("dark");
      restoreRef.current = null;
    };
    restoreRef.current = restore;
    window.addEventListener("afterprint", restore);
    window.print();
  }

  return (
    <PageHeader
      className="print:pt-0"
      kicker={kicker}
      title={title}
      description={description}
      actions={
        <div className="flex flex-wrap items-center gap-2 print:hidden">
          {prev && (
            <Button variant="outline" onClick={onPrevious}>
              <ChevronLeftIcon aria-hidden />
              {prevLabel}
            </Button>
          )}
          <Select
            items={items}
            value={current && current in items ? current : null}
            onValueChange={(v) => {
              const it = list.find((x) => histKey(x.kind, x.date) === v);
              if (it) onSelect(it.kind, it.date);
            }}
          >
            <SelectTrigger aria-label="Recap history" className="w-64 max-w-full">
              <SelectValue placeholder="History" />
            </SelectTrigger>
            <SelectContent>
              {list.map((it) => (
                <SelectItem key={histKey(it.kind, it.date)} value={histKey(it.kind, it.date)}>
                  {historyLabel(it)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" disabled={!doc} onClick={exportPdf}>
            Export PDF
          </Button>
          {canGenerate && (
            <Button loading={generating} onClick={onRegenerate}>
              ✦ Regenerate
            </Button>
          )}
        </div>
      }
    />
  );
}
