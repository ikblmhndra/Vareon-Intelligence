"use client";

import { useRef, useState, type KeyboardEvent } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { IocActionChip, IocStateChip, type IocTarget } from "@/components/intelligence/ioc/ioc-detail-body";
import { IocDetailPanel } from "@/components/intelligence/ioc/ioc-detail-panel";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { FilterSelect } from "@/components/ui/filter-select";
import { MasterDetail } from "@/components/ui/master-detail";
import { MeterBar } from "@/components/ui/meter-bar";
import { NumberedPager } from "@/components/ui/numbered-pager";
import { SearchInput } from "@/components/ui/search-input";
import { StatePanel } from "@/components/ui/state-panel";
import { StatTile } from "@/components/ui/stat-tile";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { IocListResponse, IocStats, IocSummary } from "@/lib/api/loose-types";
import { useCan } from "@/lib/auth/permissions";
import { downloadBlob } from "@/lib/csv";
import { useDebounced } from "@/lib/cve/catalog";
import { fmtAgo } from "@/lib/format";
import { defang } from "@/lib/intelligence/defang";

const IOC_TYPES = ["ip", "domain", "url", "email", "sha256", "sha1", "md5"] as const;

/** "All visible" = tanpa `state` (baris auto-suppressed tetap tersembunyi); "All incl. suppressed" = tanpa
 * `state` + `include_suppressed` (pengganti checkbox "Include suppressed" lama). */
type StateFilter = IocSummary["state"] | "all" | "all_suppressed";

const TYPE_OPTIONS = [{ value: "all", label: "all" }, ...IOC_TYPES.map((t) => ({ value: t, label: t }))];
const STATE_OPTIONS: readonly { value: StateFilter; label: string }[] = [
  { value: "active", label: "active" },
  { value: "expired", label: "expired" },
  { value: "revoked", label: "revoked" },
  { value: "allowlisted", label: "allowlisted" },
  { value: "all", label: "All visible" },
  { value: "all_suppressed", label: "All incl. suppressed" },
];
const ACTION_OPTIONS = [
  { value: "all", label: "all" },
  { value: "block_now", label: "block" },
  { value: "investigate", label: "investigate" },
  { value: "monitor", label: "monitor" },
  { value: "archive", label: "archive" },
];
const SORT_OPTIONS = [
  { value: "last_seen", label: "last seen" },
  { value: "confidence", label: "confidence" },
];
const ROWS_OPTIONS = [
  { value: "25", label: "25" },
  { value: "50", label: "50" },
  { value: "100", label: "100" },
];

/** Kata status untuk subjudul "{total} {state} · page p of n". */
const STATE_WORD: Record<StateFilter, string> = {
  active: "active",
  expired: "expired",
  revoked: "revoked",
  allowlisted: "allowlisted",
  all: "visible",
  all_suppressed: "incl. suppressed",
};

/** Statistik per tipe; dipakai juga hitungan pil "Indicators" di halaman (kunci query sama = satu fetch). */
export function useIocStats() {
  return useQuery({
    queryKey: ["intelligence", "ioc-stats"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/iocs/stats");
      if (error) throw error;
      return data as unknown as IocStats;
    },
  });
}

interface Filters {
  type: string;
  search: string;
  state: StateFilter;
  action: string;
  sort: string;
}

/** Parameter bersama daftar dan export (Task 6: export memakai aturan filter yang sama). */
function listParams(f: Filters) {
  return {
    ioc_type: f.type === "all" ? undefined : f.type,
    search: f.search || undefined,
    sort_by: f.sort === "last_seen" ? undefined : f.sort,
    actionability: f.action === "all" ? undefined : f.action,
    state: f.state === "all" || f.state === "all_suppressed" ? undefined : f.state,
    include_suppressed: f.state === "all_suppressed" ? true : undefined,
  };
}

/** Tampilan "Indicators" (spec 2b 6.9): toolbar, tile per tipe, tabel kiri + panel detail kanan. Pilihan baris
 * dipegang lokal; tanpa pilihan, baris pertama halaman yang tampil. IOC yang keluar dari daftar setelah aksi
 * (mis. FP di state active) tetap tampil di panel supaya bisa dipulihkan dengan TP. */
export function IocIndicatorsView() {
  const can = useCan();
  const [type, setType] = useState("all");
  const [searchText, setSearchText] = useState("");
  const [state, setState] = useState<StateFilter>("active");
  const [action, setAction] = useState("all");
  const [sort, setSort] = useState("last_seen");
  const [pageSize, setPageSize] = useState(50);
  const [page, setPage] = useState(1);
  const [picked, setPicked] = useState<(IocTarget & { id: number }) | null>(null);
  const [exporting, setExporting] = useState(false);
  const search = useDebounced(searchText.trim(), 300);
  const rowRefs = useRef(new Map<number, HTMLButtonElement>());
  const tableRef = useRef<HTMLDivElement>(null);

  const filters: Filters = { type, search, state, action, sort };
  const stats = useIocStats();
  const list = useQuery({
    queryKey: ["intelligence", "ioc-list", filters, pageSize, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/iocs", {
        params: { query: { ...listParams(filters), page, page_size: pageSize } },
      });
      if (error) throw error;
      return data as unknown as IocListResponse;
    },
    placeholderData: keepPreviousData,
  });

  /** Setiap perubahan filter kembali ke halaman 1 dan melepas pilihan (baris pertama jadi default). */
  function reset<T>(set: (v: T) => void) {
    return (v: T) => {
      set(v);
      setPage(1);
      setPicked(null);
    };
  }

  const rows = list.data?.iocs ?? [];
  const total = list.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const first = rows[0];
  const selected: (IocTarget & { id: number }) | null =
    picked ?? (first ? { id: first.id, type: first.type, value: first.value } : null);

  function select(ioc: IocSummary) {
    setPicked({ id: ioc.id, type: ioc.type, value: ioc.value });
  }

  // Satu tab stop untuk tabel (tombol nilai baris terpilih); panah/Home/End memindahkan sekaligus memilih.
  function onRowKey(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number;
    if (e.key === "ArrowDown") next = Math.min(rows.length - 1, index + 1);
    else if (e.key === "ArrowUp") next = Math.max(0, index - 1);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = rows.length - 1;
    else return;
    e.preventDefault();
    select(rows[next]);
    rowRefs.current.get(rows[next].id)?.focus();
  }

  const selectedInRows = rows.some((r) => r.id === selected?.id);
  const returnFocus = () => (selected ? rowRefs.current.get(selected.id) : undefined) ?? tableRef.current;

  async function exportCsv() {
    setExporting(true);
    try {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(listParams(filters))) if (v !== undefined) qs.set(k, String(v));
      const { truncated } = await downloadBlob(`/api/iocs/export?${qs}`, "iocs.csv");
      if (truncated) toast.warning("Export was cut at 50,000 rows. Narrow the filters to get every row.");
    } catch {
      toast.error("Export failed.");
    } finally {
      setExporting(false);
    }
  }

  let body;
  if (list.isPending) body = <StatePanel variant="loading" title="Loading indicators" className="mx-5" />;
  else if (list.isError)
    body = (
      <StatePanel
        variant="error"
        title="Could not load indicators"
        className="mx-5"
        action={
          <Button variant="outline" size="sm" onClick={() => void list.refetch()}>
            Retry
          </Button>
        }
      />
    );
  else if (rows.length === 0)
    body = (
      <StatePanel
        variant="empty"
        title="No indicators match these filters"
        description="Clear the search or change Type, State or Action to see more."
        className="mx-5"
      />
    );
  else
    body = (
      <div ref={tableRef} tabIndex={-1} className="outline-none">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-5">Value</TableHead>
              <TableHead>Type</TableHead>
              <TableHead className="text-right">Conf.</TableHead>
              <TableHead>Actionability</TableHead>
              <TableHead>Action</TableHead>
              <TableHead className="text-right">Seen</TableHead>
              <TableHead className="pr-5">Feedback</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((ioc, i) => {
              const isSel = ioc.id === selected?.id;
              const shown = defang(ioc.type, ioc.value);
              const tabbable = selectedInRows ? isSel : i === 0;
              return (
                <TableRow key={ioc.id} selected={isSel} className="cursor-pointer" onClick={() => select(ioc)}>
                  <TableCell className="max-w-72 pl-5">
                    {/* Tombol untuk papan-ketik; kliknya naik ke onClick baris (tidak ada elemen interaktif lain di baris). */}
                    <button
                      ref={(el) => {
                        if (el) rowRefs.current.set(ioc.id, el);
                        else rowRefs.current.delete(ioc.id);
                      }}
                      type="button"
                      tabIndex={tabbable ? 0 : -1}
                      aria-current={isSel ? "true" : undefined}
                      title={shown}
                      onKeyDown={(e) => onRowKey(e, i)}
                      className="block max-w-full truncate rounded-sm text-left font-code text-xs text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                    >
                      {shown}
                    </button>
                    {(ioc.state !== "active" || ioc.tlp !== "clear" || ioc.auto_suppressed) && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {ioc.state !== "active" && <IocStateChip state={ioc.state} />}
                        {ioc.tlp !== "clear" && <Chip kind="flag" value={`TLP:${ioc.tlp}`} />}
                        {/* filter "all + suppressed" menampilkan baris tersembunyi: tanpa chip, baris itu tak terbedakan */}
                        {ioc.auto_suppressed && (
                          <span title={ioc.suppression_reason ?? undefined}>
                            <Chip kind="flag" value="SUPPRESSED" />
                          </span>
                        )}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <Chip kind="flag" value={ioc.type} />
                  </TableCell>
                  <TableCell className="text-right font-code text-xs">
                    {ioc.confidence_score != null ? Math.round(ioc.confidence_score) : "—"}
                  </TableCell>
                  <TableCell>
                    {ioc.actionability_score != null ? (
                      <div className="w-28">
                        <MeterBar
                          value={ioc.actionability_score}
                          max={100}
                          aria-label={`Actionability of ${shown}`}
                          label={<span className="font-code text-foreground">{ioc.actionability_score}</span>}
                        />
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <IocActionChip label={ioc.actionability_label} />
                  </TableCell>
                  <TableCell className="text-right font-code text-xs text-muted-foreground" title={`last seen ${fmtAgo(ioc.last_seen)}`}>
                    {ioc.seen_count || 1}
                  </TableCell>
                  <TableCell className="pr-5 text-xs whitespace-nowrap text-muted-foreground">
                    {ioc.tp_count} TP · {ioc.fp_count} FP
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        <div className="flex flex-wrap items-end justify-between gap-3 px-5">
          <FilterSelect
            prefix="Rows"
            value={String(pageSize)}
            onChange={(v) => reset(setPageSize)(Number(v))}
            options={ROWS_OPTIONS}
            aria-label="Rows per page"
          />
          <NumberedPager page={page} totalPages={totalPages} onPageChange={setPage} label="Indicators pagination" />
        </div>
        {state !== "allowlisted" && state !== "all_suppressed" && (
          <p className="px-5 pt-3 text-2xs text-muted-foreground">
            Indicators auto-suppressed by the allowlist are hidden. Choose State: allowlisted or All incl. suppressed to see them.
          </p>
        )}
      </div>
    );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          className="w-56"
          value={searchText}
          onChange={reset(setSearchText)}
          placeholder="Search value"
          aria-label="Search indicator value"
        />
        <FilterSelect prefix="Type" value={type} onChange={reset(setType)} options={TYPE_OPTIONS} />
        <FilterSelect prefix="State" value={state} onChange={reset(setState)} options={STATE_OPTIONS} />
        <FilterSelect prefix="Action" value={action} onChange={reset(setAction)} options={ACTION_OPTIONS} />
        <FilterSelect prefix="Sort" value={sort} onChange={reset(setSort)} options={SORT_OPTIONS} />
        {can("export_data") && (
          <Button variant="outline" size="sm" className="ml-auto" loading={exporting} onClick={() => void exportCsv()}>
            Export CSV
          </Button>
        )}
      </div>

      {stats.data && stats.data.by_type.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
          {stats.data.by_type.map((t) => (
            <StatTile
              key={t.type}
              label={t.type}
              value={t.count.toLocaleString()}
              selected={type === t.type}
              onSelect={() => reset(setType)(type === t.type ? "all" : t.type)}
            />
          ))}
        </div>
      )}

      <MasterDetail
        list={
          <Card>
            <div className="px-5">
              <h2 className="font-heading text-base font-semibold">Indicators</h2>
              <p className="text-xs text-muted-foreground">
                {total.toLocaleString()} {STATE_WORD[state]} · page {page} of {totalPages}
              </p>
            </div>
            {body}
          </Card>
        }
        detail={
          <IocDetailPanel
            target={selected ? { type: selected.type, value: selected.value } : null}
            // Pilihan bawaan (baris pertama) disematkan setelah aksi: FP di state active mengeluarkan baris dari
            // daftar, dan panel + peringatan FP sumber harus tetap pada IOC itu supaya bisa dipulihkan dengan TP.
            onChanged={() => selected && setPicked(selected)}
            onDeleted={() => setPicked(null)}
            returnFocus={returnFocus}
          />
        }
      />
    </div>
  );
}
