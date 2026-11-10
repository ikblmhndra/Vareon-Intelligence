"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import Markdown from "react-markdown";

import { BarSeries } from "@/components/ui/bar-series";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { RowMenu } from "@/components/ui/row-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api/client";
import { fmtShortDate } from "@/lib/format";
import { displayId } from "@/lib/intelligence/format";
import type { PIROut } from "@/lib/intelligence/pir";

import { PirCriteriaRows, PirPriorityChip } from "./pir-list";

const linkClass =
  "rounded-sm font-semibold text-primary-text underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

// Deskripsi lebih panjang dari ini dilipat (spec 6.4 "collapsible when long").
const LONG_DESCRIPTION = 280;

interface PirDetailCardProps {
  pir: PIROut;
  /** Varian `include_campaigns=true` (query latar); hanya baris "Campaigns matched" yang membacanya. */
  campaigns: UseQueryResult<PIROut[]>;
  canManage: boolean;
  canExport: boolean;
  exportingJson: boolean;
  onViewArticles: () => void;
  onExportJson: () => void;
  onExportDocx: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

/** Panel kanan PIR terpilih (spec 2b 6.4): grafik cakupan mingguan, baris ringkas (artikel, RFI tertaut,
 * kampanye, periode), deskripsi, dan aksi. */
export function PirDetailCard({
  pir,
  campaigns,
  canManage,
  canExport,
  exportingJson,
  onViewArticles,
  onExportJson,
  onExportDocx,
  onEdit,
  onDelete,
}: PirDetailCardProps) {
  const id = displayId("PIR", pir.id);
  const weekly = useQuery({
    queryKey: ["pir", "weekly", pir.id],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pir/{pir_id}/coverage/weekly", {
        params: { path: { pir_id: pir.id }, query: { weeks: 12 } },
      });
      if (error) throw error;
      return data;
    },
  });
  const weeks = weekly.data?.weeks ?? [];

  return (
    <Card>
      <div className="flex flex-col gap-4 px-5">
        <div>
          <h2 className="font-heading text-lg font-semibold">
            <span className="font-code">{id}</span> coverage
          </h2>
          <p className="text-xs text-muted-foreground">
            {weekly.data?.since
              ? `Articles matched per week, since ${fmtShortDate(weekly.data.since)}`
              : "Articles matched per week"}
          </p>
        </div>

        {weekly.isPending ? (
          <StatePanel variant="loading" title="Loading coverage" className="py-8" />
        ) : weekly.isError ? (
          <StatePanel
            variant="error"
            title="Failed to load coverage"
            className="py-8"
            action={
              <Button variant="outline" size="sm" onClick={() => void weekly.refetch()}>
                Retry
              </Button>
            }
          />
        ) : weeks.length === 0 ? (
          // Backend mengembalikan minggu kosong untuk PIR yang tanggal mulainya belum tiba.
          <StatePanel variant="empty" title="No weeks to show yet" description="The PIR period has not started." className="py-8" />
        ) : (
          <BarSeries
            labels={weeks.map((w) => fmtShortDate(w.week_start))}
            values={weeks.map((w) => w.count)}
            tone="primary"
            highlightLast={pir.is_gap ? 2 : undefined}
            highlightTone="destructive"
            height={160}
            aria-label={`Articles matched per week for ${id}`}
            formatValue={(v) => `${v} articles`}
          />
        )}

        <dl className="flex flex-col divide-y divide-border text-sm">
          <Row label="Matched articles">
            <span className="font-semibold">{pir.coverage_count.toLocaleString()}</span>
          </Row>
          <Row label="Linked RFIs">
            <LinkedRfis pir={pir} />
          </Row>
          <Row label="Campaigns matched">
            <MatchedCampaigns pir={pir} campaigns={campaigns} />
          </Row>
          <Row label="Period">
            <span className="font-semibold">{period(pir.start_date, pir.end_date)}</span>
          </Row>
        </dl>

        <PirCriteriaRows criteria={pir.criteria} />
        <div className="flex items-center gap-2">
          <PirPriorityChip priority={pir.priority} />
          {pir.owner && <span className="text-xs text-muted-foreground">Owner: {pir.owner}</span>}
        </div>

        {pir.description && <Description text={pir.description} />}

        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={onViewArticles}>
            View articles
          </Button>
          {canExport && (
            <Button variant="outline" size="sm" loading={exportingJson} onClick={onExportJson}>
              Export JSON
            </Button>
          )}
          <RowMenu
            label={`More actions for ${id}`}
            items={[
              { label: "Export DOCX", onSelect: onExportDocx, hidden: !canExport },
              { label: "Edit", onSelect: onEdit, hidden: !canManage },
              { label: "Delete", onSelect: onDelete, destructive: true, hidden: !canManage },
            ]}
          />
        </div>
      </div>
    </Card>
  );
}

/** Kartu statis penjelasan gap (C9: ditulis ulang dari `compute_coverage`, aturan 14 hari D16). */
export function PirGapCard() {
  return (
    <Card>
      <div className="flex flex-col gap-2 px-5">
        <h2 className="font-heading text-lg font-semibold">What a coverage gap means</h2>
        <p className="text-sm text-muted-foreground">
          A PIR shows COVERAGE GAP when it has matched articles before but none in the last 14 days. A PIR without
          criteria always shows a gap.
        </p>
      </div>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right">{children}</dd>
    </div>
  );
}

function period(start: string | null | undefined, end: string | null | undefined): string {
  if (!start && !end) return "open-ended";
  return `${start ? fmtShortDate(start) : "—"} - ${end ? fmtShortDate(end) : "open-ended"}`;
}

/** "{n} open" menuju halaman RFI tersaring PIR ini; tooltip mendaftar RFI tertaut (maks. 20 dari backend). */
function LinkedRfis({ pir }: { pir: PIROut }) {
  const href = `/intelligence/rfi?pir=${pir.id}`;
  const text = `${pir.linked_rfi_open} open`;
  const label = `${text} linked RFIs for ${displayId("PIR", pir.id)}`;
  if (pir.linked_rfis.length === 0) {
    return (
      <Link href={href} aria-label={label} className={linkClass}>
        {text}
      </Link>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger render={<Link href={href} aria-label={label} className={linkClass} />}>{text}</TooltipTrigger>
      <TooltipContent side="left" className="flex-col items-start">
        {pir.linked_rfis.map((r) => (
          <span key={r.id} className="block max-w-xs truncate">
            <span className="font-code">{displayId("RFI", r.id)}</span> {r.status.replace("_", " ")} · {r.question}
          </span>
        ))}
        {pir.linked_rfis.length >= 20 && <span className="block">Showing the first 20</span>}
      </TooltipContent>
    </Tooltip>
  );
}

/** Kampanye cocok hanya dihitung untuk PIR aktif (`_match_pirs` memakai `list_active_by_client`), jadi PIR lain
 * diberi tahu alih-alih "none" yang menyesatkan. */
function MatchedCampaigns({ pir, campaigns }: { pir: PIROut; campaigns: UseQueryResult<PIROut[]> }) {
  if (pir.status !== "active") {
    return <span className="text-muted-foreground">Only active PIRs are matched to campaigns</span>;
  }
  if (campaigns.isPending) return <Skeleton role="status" aria-label="Loading campaigns" className="ml-auto h-4 w-32" />;
  if (campaigns.isError) return <span className="text-muted-foreground">Could not load campaigns</span>;
  const list = campaigns.data.find((p) => p.id === pir.id)?.matched_campaigns ?? [];
  if (list.length === 0) return <span className="text-muted-foreground">none in the last 30 days</span>;
  return (
    <ul className="flex flex-col items-end gap-1">
      {list.map((c) => (
        <li key={c.cluster_id}>
          <Link
            href={`/intelligence/campaign-clusters?id=${encodeURIComponent(c.cluster_id)}&days=30`}
            className={linkClass}
          >
            {c.title}
          </Link>
        </li>
      ))}
    </ul>
  );
}

function Description({ text }: { text: string }) {
  const long = text.length > LONG_DESCRIPTION;
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="flex flex-col items-start gap-1">
      <div className={long && !expanded ? "max-h-24 overflow-hidden" : undefined}>
        <div className="prose prose-sm max-w-none text-sm">
          <Markdown
            components={{
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noreferrer">
                  {children}
                </a>
              ),
            }}
          >
            {text}
          </Markdown>
        </div>
      </div>
      {long && (
        <Button variant="link" size="xs" className="px-0" aria-expanded={expanded} onClick={() => setExpanded((e) => !e)}>
          {expanded ? "Show less" : "Show more"}
        </Button>
      )}
    </div>
  );
}
