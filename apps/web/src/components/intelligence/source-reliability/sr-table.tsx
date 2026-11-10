"use client";

import { ArrowDownIcon, ArrowUpIcon, ChevronsUpDownIcon } from "lucide-react";
import { useState } from "react";

import { SrGrid } from "@/components/intelligence/source-reliability/sr-grid";
import {
  gradeChipClass,
  SR_SORT_LABEL,
  type SREntry,
  type SrSortCol,
  type SrSortDir,
} from "@/components/intelligence/source-reliability/sr-model";
import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { NumberedPager } from "@/components/ui/numbered-pager";
import { RowMenu } from "@/components/ui/row-menu";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { StatePanel } from "@/components/ui/state-panel";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { fmtCompactAge, fmtShortDate } from "@/lib/format";
import { originLabel } from "@/lib/intelligence/format";

export const SR_PAGE_SIZE = 25;

const MODES = [
  { value: "table", label: "Table" },
  { value: "grid", label: "Grid" },
] as const;

interface RowActions {
  /** Klik baris / nama sumber: buka dialog (ubah bila `manage_sources`, baca-saja bila tidak). */
  onOpen: (entry: SREntry) => void;
  onEdit: (entry: SREntry) => void;
  onRemove: (entry: SREntry) => void;
  canManage: boolean;
}

interface SrSortHeaderProps {
  col: SrSortCol;
  label: string;
  sortBy: SrSortCol;
  sortDir: SrSortDir;
  onSort: (col: SrSortCol) => void;
}

/** Kepala kolom yang bisa diurut: `aria-sort` di `<th>`, pemicunya `<button>` supaya terjangkau papan-ketik. */
function SortHeader({ col, label, sortBy, sortDir, onSort }: SrSortHeaderProps) {
  const active = sortBy === col;
  const Icon = !active ? ChevronsUpDownIcon : sortDir === "asc" ? ArrowUpIcon : ArrowDownIcon;
  return (
    <TableHead aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        onClick={() => onSort(col)}
        className="inline-flex items-center gap-1 rounded-sm uppercase outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        {label}
        <Icon aria-hidden className="size-3" />
      </button>
    </TableHead>
  );
}

interface SrTableProps extends RowActions {
  entries: SREntry[];
  reliability: Record<string, string>;
  sortBy: SrSortCol;
  sortDir: SrSortDir;
  onSort: (col: SrSortCol) => void;
}

/** Tabel sumber. Baris bisa diklik (D7) tapi tidak menyarangkan tombol di tombol: nama sumber adalah
 * `<button>` untuk papan-ketik (kliknya naik ke `onClick` baris), `onClick` baris untuk mouse, dan `RowMenu` ada di sel sendiri. */
export function SrTable({ entries, reliability, sortBy, sortDir, onSort, ...actions }: SrTableProps) {
  const sortProps = { sortBy, sortDir, onSort };
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <SortHeader col="source_name" label="Source" {...sortProps} />
          <SortHeader col="reliability_grade" label="Admiralty" {...sortProps} />
          <TableHead>Reliability</TableHead>
          <TableHead>Kind</TableHead>
          <TableHead>Origin</TableHead>
          <SortHeader col="analyst_name" label="Analyst" {...sortProps} />
          <SortHeader col="last_updated" label="Updated" {...sortProps} />
          <TableHead>
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map((e) => (
          <TableRow key={e.id} className="cursor-pointer" onClick={() => actions.onOpen(e)}>
            <TableCell className="max-w-64 px-4 text-xs whitespace-normal">
              <button
                type="button"
                className="rounded-sm text-left font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                {e.source_name}
              </button>
            </TableCell>
            <TableCell className="px-4">
              <Chip kind="grade" value={e.admiralty_code} className={gradeChipClass(e.reliability_grade)} />
            </TableCell>
            <TableCell className="px-4 text-xs text-muted-foreground">{reliability[e.reliability_grade] ?? "—"}</TableCell>
            <TableCell className="px-4">{e.content_kind ? <Chip kind="flag" value={e.content_kind} /> : "—"}</TableCell>
            <TableCell
              className="px-4 text-xs text-muted-foreground"
              title={e.origin === "default" ? "Default grade for this source kind; not set by an analyst" : undefined}
            >
              {originLabel(e.origin)}
            </TableCell>
            <TableCell className="px-4 text-xs text-muted-foreground">{e.analyst_name}</TableCell>
            <TableCell className="px-4 text-xs whitespace-nowrap text-muted-foreground" title={fmtShortDate(e.last_updated)}>
              {fmtCompactAge(e.last_updated || e.added_date)}
            </TableCell>
            <TableCell className="px-2" onClick={(ev) => ev.stopPropagation()}>
              <RowMenu
                label={`Actions for ${e.source_name}`}
                items={[
                  { label: "Edit", onSelect: () => actions.onEdit(e), hidden: !actions.canManage },
                  { label: "Remove", onSelect: () => actions.onRemove(e), destructive: true, hidden: !actions.canManage },
                ]}
              />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

interface SrSourcesCardProps extends RowActions {
  state: "loading" | "error" | "ready";
  onRetry: () => void;
  entries: SREntry[];
  total: number;
  reliability: Record<string, string>;
  page: number;
  onPageChange: (page: number) => void;
  sortBy: SrSortCol;
  sortDir: SrSortDir;
  onSort: (col: SrSortCol) => void;
  filtered: boolean;
}

/** Kartu "Sources": subjudul, pilihan Table/Grid, isi, dan pager bernomor. Data dan state filter dimiliki
 * halaman karena hitungan pil toolbar dan kartu samping membacanya juga. */
export function SrSourcesCard(props: SrSourcesCardProps) {
  const { state, entries, total, page } = props;
  const [mode, setMode] = useState<"table" | "grid">("table");
  const totalPages = Math.max(1, Math.ceil(total / SR_PAGE_SIZE));
  const from = total === 0 ? 0 : (page - 1) * SR_PAGE_SIZE + 1;
  const to = Math.min(total, page * SR_PAGE_SIZE);

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5">
        <div>
          <h2 className="font-heading text-base font-semibold">Sources</h2>
          <p className="text-xs text-muted-foreground">
            {total} source{total === 1 ? "" : "s"} · sorted by {SR_SORT_LABEL[props.sortBy]}
          </p>
        </div>
        <SegmentedControl aria-label="Sources view" options={MODES} value={mode} onChange={setMode} />
      </div>
      <div className="px-2">
        {state === "loading" && <StatePanel variant="loading" title="Loading sources" className="mx-3" />}
        {state === "error" && (
          <StatePanel
            variant="error"
            title="Could not load sources"
            className="mx-3"
            action={
              <Button variant="outline" size="sm" onClick={props.onRetry}>
                Retry
              </Button>
            }
          />
        )}
        {state === "ready" && entries.length === 0 && (
          <StatePanel
            variant="empty"
            title={props.filtered ? "No sources match these filters" : "No sources rated yet"}
            description={props.filtered ? "Clear the search, grade or origin filter to see more." : undefined}
            className="mx-3"
          />
        )}
        {state === "ready" && entries.length > 0 && (
          <>
            {mode === "table" ? (
              <SrTable
                entries={entries}
                reliability={props.reliability}
                sortBy={props.sortBy}
                sortDir={props.sortDir}
                onSort={props.onSort}
                onOpen={props.onOpen}
                onEdit={props.onEdit}
                onRemove={props.onRemove}
                canManage={props.canManage}
              />
            ) : (
              <SrGrid
                entries={entries}
                reliability={props.reliability}
                onOpen={props.onOpen}
                onEdit={props.onEdit}
                onRemove={props.onRemove}
                canManage={props.canManage}
              />
            )}
            <div className="px-3 pb-1">
              <NumberedPager
                page={page}
                totalPages={totalPages}
                onPageChange={props.onPageChange}
                label="Sources pagination"
                summary={`Showing ${from}-${to} of ${total}`}
              />
            </div>
          </>
        )}
      </div>
    </Card>
  );
}
