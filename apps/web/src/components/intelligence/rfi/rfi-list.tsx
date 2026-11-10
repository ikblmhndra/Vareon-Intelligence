"use client";

import Link from "next/link";

import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { LoadMoreFooter } from "@/components/ui/load-more-footer";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useRovingKeys } from "@/components/ui/use-roving-keys";
import { fmtShortDate } from "@/lib/format";
import { displayId } from "@/lib/intelligence/format";
import { DUE_TONE_CLASS, dueInfo, type RFIOut } from "@/lib/intelligence/rfi";
import { cn } from "@/lib/utils";

/** Lencana status RFI: open merah, in progress primer, closed netral (selaras dengan tab). */
export function RfiStatusChip({ status }: { status: string }) {
  if (status === "open" || status === "in_progress") {
    return <Chip kind="status" value={status} />;
  }
  return (
    <Chip kind="flag" value={status}>
      {status.replace("_", " ")}
    </Chip>
  );
}

interface RfiListProps {
  rfis: RFIOut[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  shown: number;
  total: number;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}

/** Kartu "Requests" (spec 2b 6.5): tabel RFI urut jatuh tempo terdekat. Pemilihan lewat tombol di sel
 * pertanyaan (panah/Home/End memindahkan sekaligus memilih) dan klik di mana pun pada baris. Tautan PIR
 * adalah sel sendiri dan menghentikan klik supaya tidak ikut memilih baris. */
export function RfiList({ rfis, selectedId, onSelect, shown, total, hasMore, loadingMore, onLoadMore }: RfiListProps) {
  const items = rfis.map((r) => ({ value: String(r.id) }));
  const { onKeyDown, setRef, tabIndexFor } = useRovingKeys(
    items,
    selectedId != null ? String(selectedId) : "",
    (v) => onSelect(Number(v)),
  );

  return (
    <Card>
      <div className="flex flex-col gap-3 px-5">
        <div>
          <h2 className="font-heading text-lg font-semibold">Requests</h2>
          <p className="text-xs text-muted-foreground">Due soonest first</p>
        </div>
        <Table
          aria-label="Requests for information"
          onKeyDown={(e) => {
            // Tautan PIR juga ada di tabel; hanya tombol pertanyaan yang memakai panah untuk berpindah baris.
            if ((e.target as HTMLElement).closest("[data-rfi-select]")) onKeyDown(e);
          }}
        >
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Question</TableHead>
              <TableHead>Requester</TableHead>
              <TableHead>PIR</TableHead>
              <TableHead>Due</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rfis.map((r, i) => {
              const selected = r.id === selectedId;
              const due = dueInfo(r.due_date, r.status);
              return (
                <TableRow key={r.id} selected={selected} className="cursor-pointer" onClick={() => onSelect(r.id)}>
                  <TableCell className="max-w-72 min-w-48 whitespace-normal">
                    <button
                      ref={setRef(i)}
                      type="button"
                      data-rfi-select=""
                      tabIndex={tabIndexFor(i)}
                      aria-current={selected ? "true" : undefined}
                      className="line-clamp-2 rounded-sm text-left text-xs font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                    >
                      {r.question}
                    </button>
                  </TableCell>
                  <TableCell className="max-w-32 truncate text-xs">{r.requester}</TableCell>
                  <TableCell className="text-xs">
                    {r.linked_pir != null ? (
                      <Link
                        href={`/intelligence/pir?id=${r.linked_pir}`}
                        aria-label={`Open ${displayId("PIR", r.linked_pir)}`}
                        onClick={(e) => e.stopPropagation()}
                        className="rounded-sm font-code font-semibold text-primary-text underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                      >
                        {displayId("PIR", r.linked_pir)}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell className={cn("text-xs", due && DUE_TONE_CLASS[due.tone])}>
                    {fmtShortDate(r.due_date)}
                  </TableCell>
                  <TableCell>
                    <RfiStatusChip status={r.status} />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        <LoadMoreFooter shown={shown} total={total} hasMore={hasMore} loading={loadingMore} onLoadMore={onLoadMore} />
      </div>
    </Card>
  );
}
