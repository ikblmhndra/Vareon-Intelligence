import { PageHeader } from "@/components/page-header";
import { SegmentedControl } from "@/components/ui/segmented-control";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";
import { execCountNoun, type ExecFilters, type ExecView } from "@/lib/exec/filters";
import { fmtAgo, fmtShortDate } from "@/lib/format";

const VIEW_OPTIONS = [
  { value: "briefing", label: "Briefing" },
  { value: "board", label: "Analyst board" },
] as const;

interface ExecPageHeaderProps {
  days: number;
  today: Date;
  /** Kosong selama data belum ada: baris deskripsi hanya memuat rentang tanggal. */
  data?: ExecDashboardV2;
  /** `dataUpdatedAt` react-query (ms); 0 = belum pernah berhasil. */
  updatedAt: number;
  /** Penentu kata benda hitungan ("threat news articles" / "articles" / "confirmed incidents"). */
  filters: Pick<ExecFilters, "incidentOnly" | "confirmedOnly">;
  view: ExecView;
  onViewChange: (v: ExecView) => void;
}

/** Header halaman Exec (kedua tampilan): judul mengikuti periode, deskripsi satu baris, pemilih tampilan. */
export function ExecPageHeader({ days, today, data, updatedAt, filters, view, onViewChange }: ExecPageHeaderProps) {
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate() - days);
  const parts = [`${fmtShortDate(start)} – ${fmtShortDate(today, { withYear: true })}`];
  if (data) {
    parts.push(`${data.total_incidents.toLocaleString()} ${execCountNoun(filters)}`);
    parts.push(`${data.unique_ta_count.toLocaleString()} threat actors`);
  }
  if (updatedAt > 0) parts.push(`updated ${fmtAgo(new Date(updatedAt))}`);
  return (
    <PageHeader
      kicker="EXECUTIVE"
      title={`Threat posture, last ${days} days`}
      description={parts.join(" · ")}
      actions={
        <SegmentedControl options={VIEW_OPTIONS} value={view} onChange={onViewChange} aria-label="Exec view" />
      }
    />
  );
}
