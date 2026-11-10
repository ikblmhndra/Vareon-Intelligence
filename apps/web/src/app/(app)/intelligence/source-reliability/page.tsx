"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { SrAside } from "@/components/intelligence/source-reliability/sr-aside";
import { SrEntryDialog } from "@/components/intelligence/source-reliability/sr-entry-dialog";
import {
  invalidateSr,
  useSrLabels,
  useSrReview,
  type SREntry,
  type SrSortCol,
  type SrSortDir,
} from "@/components/intelligence/source-reliability/sr-model";
import { SrReviewTable } from "@/components/intelligence/source-reliability/sr-review-table";
import { SR_PAGE_SIZE, SrSourcesCard } from "@/components/intelligence/source-reliability/sr-table";
import { Button } from "@/components/ui/button";
import { FilterSelect } from "@/components/ui/filter-select";
import { SearchInput } from "@/components/ui/search-input";
import { TabPills } from "@/components/ui/tab-pills";
import { api } from "@/lib/api/client";
import type { SrActionResult } from "@/lib/api/loose-types";
import { useCan } from "@/lib/auth/permissions";
import { downloadBlob } from "@/lib/csv";

type View = "all" | "review";
type Origin = "all" | "default" | "analyst";

const GRADE_OPTIONS = [
  { value: "all", label: "all" },
  ...["A", "B", "C", "D", "E", "F"].map((g) => ({ value: g, label: g })),
];

const ORIGIN_OPTIONS: readonly { value: Origin; label: string }[] = [
  { value: "all", label: "all" },
  { value: "default", label: "auto" },
  { value: "analyst", label: "analyst" },
];

/** Source Reliability (spec 2b 6.2). Halaman memegang filter, urutan, halaman, dan query daftar karena
 * hitungan pil, kartu samping, dan ekspor CSV semuanya membacanya; kartu-kartunya murni tampilan. */
export default function SourceReliabilityPage() {
  const can = useCan();
  const queryClient = useQueryClient();
  const manage = can("manage_sources");
  const [view, setView] = useState<View>("all");
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [grade, setGrade] = useState("all");
  const [origin, setOrigin] = useState<Origin>("all");
  const [sortBy, setSortBy] = useState<SrSortCol>("last_updated");
  const [sortDir, setSortDir] = useState<SrSortDir>("desc");
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  const [openEntry, setOpenEntry] = useState<SREntry | null>(null);
  const [editEntry, setEditEntry] = useState<SREntry | null>(null);
  const [removeTarget, setRemoveTarget] = useState<SREntry | null>(null);
  const [removing, setRemoving] = useState(false);
  const [exporting, setExporting] = useState(false);

  const entriesQuery = useQuery({
    queryKey: ["intelligence", "sr-entries", page, search, grade, origin, sortBy, sortDir],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/sr/entries", {
        params: {
          query: {
            page,
            page_size: SR_PAGE_SIZE,
            sort_by: sortBy,
            sort_dir: sortDir,
            search: search || undefined,
            grade: grade === "all" ? undefined : grade,
            origin: origin === "all" ? undefined : origin,
          },
        },
      });
      if (error) throw error;
      return data;
    },
  });
  // Hitungan "Needs review" hanya diminta bila pengguna boleh melihat antreannya (endpoint 403 tanpa izin).
  const reviewQuery = useSrReview(manage);
  const labels = useSrLabels();

  const entries = entriesQuery.data?.entries ?? [];
  const total = entriesQuery.data?.total ?? 0;
  const filtered = search !== "" || grade !== "all" || origin !== "all";

  /** Ubah filter selalu kembali ke halaman 1, supaya tidak mendarat di halaman yang sudah tidak ada. */
  function resetPage<T>(set: (v: T) => void) {
    return (v: T) => {
      set(v);
      setPage(1);
    };
  }

  function onSort(col: SrSortCol) {
    if (sortBy === col) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortBy(col);
      setSortDir(col === "last_updated" ? "desc" : "asc");
    }
    setPage(1);
  }

  async function removeEntry(target: SREntry) {
    setRemoving(true);
    // finally: dialog harus tertutup dan tombol bebas dari status memuat walau fetch melempar.
    try {
      const { data, error } = await api.DELETE("/api/sr/entries/{entry_id}", {
        params: { path: { entry_id: target.id } },
      });
      if (error || !(data as unknown as SrActionResult).success) {
        toast.error("Delete failed.");
        return;
      }
      toast.success("Removed.");
      // Baris terakhir di halaman terakhir hilang: mundur satu halaman agar tidak mendarat di halaman kosong.
      if (entries.length === 1 && page > 1) setPage(page - 1);
      invalidateSr(queryClient);
    } catch {
      toast.error("Delete failed.");
    } finally {
      setRemoving(false);
      setRemoveTarget(null);
    }
  }

  async function exportCsv() {
    setExporting(true);
    try {
      const qs = new URLSearchParams({ sort_by: sortBy, sort_dir: sortDir });
      if (search) qs.set("search", search);
      if (grade !== "all") qs.set("grade", grade);
      if (origin !== "all") qs.set("origin", origin);
      const { truncated } = await downloadBlob(`/api/sr/entries/export?${qs}`, "source-reliability.csv");
      if (truncated) toast.warning("Export was cut at the server row limit. Narrow the filters to get every row.");
    } catch {
      toast.error("Export failed.");
    } finally {
      setExporting(false);
    }
  }

  const tabs = [
    { value: "all" as const, label: "All sources", count: entriesQuery.data?.total },
    ...(manage ? [{ value: "review" as const, label: "Needs review", count: reviewQuery.data?.length }] : []),
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <TabPills aria-label="Source reliability views" items={tabs} value={view} onChange={setView} />
        {view === "all" && (
          <>
            <SearchInput
              className="w-56"
              value={search}
              onChange={resetPage(setSearch)}
              placeholder="Search source name"
              aria-label="Search source name"
            />
            <FilterSelect prefix="Grade" value={grade} onChange={resetPage(setGrade)} options={GRADE_OPTIONS} />
            <FilterSelect prefix="Origin" value={origin} onChange={resetPage(setOrigin)} options={ORIGIN_OPTIONS} />
          </>
        )}
        <div className="ml-auto flex items-center gap-2">
          {view === "all" && can("export_data") && (
            <Button variant="outline" size="sm" loading={exporting} onClick={() => void exportCsv()}>
              Export CSV
            </Button>
          )}
          {manage && (
            <Button
              size="sm"
              onClick={() => {
                setAddKey((k) => k + 1);
                setAddOpen(true);
              }}
            >
              + Add source
            </Button>
          )}
        </div>
      </div>

      {view === "review" && manage ? (
        <SrReviewTable />
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[3fr_2fr]">
          <SrSourcesCard
            state={entriesQuery.isPending ? "loading" : entriesQuery.isError ? "error" : "ready"}
            onRetry={() => void entriesQuery.refetch()}
            entries={entries}
            total={total}
            reliability={labels.data?.reliability ?? {}}
            page={page}
            onPageChange={setPage}
            sortBy={sortBy}
            sortDir={sortDir}
            onSort={onSort}
            filtered={filtered}
            canManage={manage}
            onOpen={(e) => (manage ? setEditEntry(e) : setOpenEntry(e))}
            onEdit={setEditEntry}
            onRemove={setRemoveTarget}
          />
          <SrAside grade={grade} onGradeChange={resetPage(setGrade)} />
        </div>
      )}

      <SrEntryDialog
        key={`add-${addKey}`}
        mode="add"
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onSaved={() => invalidateSr(queryClient)}
      />
      <SrEntryDialog
        key={`edit-${editEntry?.id ?? "none"}`}
        mode="edit"
        entry={editEntry}
        open={editEntry !== null}
        onClose={() => setEditEntry(null)}
        onSaved={() => invalidateSr(queryClient)}
      />
      <SrEntryDialog
        key={`view-${openEntry?.id ?? "none"}`}
        mode="edit"
        readOnly
        entry={openEntry}
        open={openEntry !== null}
        onClose={() => setOpenEntry(null)}
        onSaved={() => undefined}
      />
      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title="Remove source rating"
        description={`Remove the source rating for "${removeTarget?.source_name}"?`}
        confirmLabel="Remove"
        tone="danger"
        confirmLoading={removing}
        onConfirm={() => removeTarget && void removeEntry(removeTarget)}
      />
    </div>
  );
}
