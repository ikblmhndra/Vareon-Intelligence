"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimplePager } from "@/components/pager";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { cn } from "@/lib/utils";
import { GRADE_BADGE_CLASS } from "@/lib/intelligence/format";
import type { components } from "@/lib/api/schema";
import type { SrActionResult } from "@/lib/api/loose-types";
import { SrEntryDialog } from "@/components/intelligence/source-reliability/sr-entry-dialog";
import { useCan } from "@/lib/auth/permissions";

type SREntry = components["schemas"]["SREntryOut"];

const PAGE_SIZE = 50;
const ALL = "__all__";
const GRADES = ["A", "B", "C", "D", "E", "F"];
type SortCol = "source_name" | "analyst_name" | "reliability_grade" | "last_updated";

/** Port `source_reliability.js` (327 baris) -- tabel grading Admiralty
 * manual analis (beda dari `source_score.py`'s heuristik otomatis,
 * `GET /api/source-scores` -- endpoint itu KONFIRMASI dead code, gak
 * ada satu pun call site di `intel.js`/file lain, `loadSourceScores()`
 * cuma di-DEFINE gak pernah DIPANGGIL, jadi sengaja gak diporting,
 * sama presedennya kayak `wisemap_service.py`). */
export function SrTable() {
  const can = useCan();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [grade, setGrade] = useState("");
  const [sortBy, setSortBy] = useState<SortCol>("source_name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  const [editEntry, setEditEntry] = useState<SREntry | null>(null);
  const [removeTarget, setRemoveTarget] = useState<SREntry | null>(null);

  const listQuery = useQuery({
    queryKey: ["intelligence", "sr-entries", page, search, grade, sortBy, sortDir],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/sr/entries", {
        params: {
          query: {
            page,
            page_size: PAGE_SIZE,
            sort_by: sortBy,
            sort_dir: sortDir,
            search: search || undefined,
            grade: grade || undefined,
          },
        },
      });
      if (error) throw error;
      return data;
    },
  });

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["intelligence", "sr-entries"] });
    void queryClient.invalidateQueries({ queryKey: ["intelligence", "ungraded-sources"] });
  }

  async function removeEntry(id: number) {
    const { data, error } = await api.DELETE("/api/sr/entries/{entry_id}", { params: { path: { entry_id: id } } });
    if (error) {
      toast.error("Delete failed");
      return;
    }
    const d = data as unknown as SrActionResult;
    if (!d.success) {
      toast.error("Delete failed.");
      return;
    }
    toast.success("Removed.");
    invalidate();
  }

  function sortHeader(col: SortCol, label: string) {
    return (
      <TableHead
        className="cursor-pointer select-none whitespace-nowrap"
        onClick={() => {
          if (sortBy === col) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
          else {
            setSortBy(col);
            setSortDir("asc");
          }
          setPage(1);
        }}
      >
        {label} <span className="text-muted-foreground">{sortBy === col ? (sortDir === "asc" ? "↑" : "↓") : "↕"}</span>
      </TableHead>
    );
  }

  const total = listQuery.data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-2 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Search</Label>
          <Input
            placeholder="Source name…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="w-48 font-mono text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Grade</Label>
          <Select
            items={{ [ALL]: "All Grades", ...Object.fromEntries(GRADES.map((g) => [g, g])) }}
            value={grade || ALL}
            onValueChange={(v) => {
              setGrade(v === ALL ? "" : (v ?? ""));
              setPage(1);
            }}
          >
            <SelectTrigger size="sm" className="w-32 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL} className="font-mono text-xs">
                All Grades
              </SelectItem>
              {GRADES.map((g) => (
                <SelectItem key={g} value={g} className="font-mono text-xs">
                  {g}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {can("manage_sources") && (
          <Button
            size="sm"
            className="ml-auto"
            onClick={() => {
              setAddKey((k) => k + 1);
              setAddOpen(true);
            }}
          >
            + Add Source Rating
          </Button>
        )}
      </div>

      {listQuery.isPending && <p className="py-8 text-center text-xs text-muted-foreground">Loading…</p>}
      {listQuery.isError && <p className="py-8 text-center text-xs text-destructive">Failed to load.</p>}

      {listQuery.data && (
        <>
          <p className="mb-2 font-mono text-xs text-muted-foreground">
            {total} source{total !== 1 ? "s" : ""} rated
          </p>
          <Table framed>
            <TableHeader>
              <TableRow>
                {sortHeader("source_name", "Source")}
                {sortHeader("analyst_name", "Analyst")}
                <TableHead>Admiralty</TableHead>
                {sortHeader("reliability_grade", "Grade")}
                <TableHead>Credibility</TableHead>
                <TableHead>Notes</TableHead>
                {sortHeader("last_updated", "Last Updated")}
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {listQuery.data.entries.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="py-8 text-center text-xs text-muted-foreground">
                    No entries found
                  </TableCell>
                </TableRow>
              )}
              {listQuery.data.entries.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="text-xs">{e.source_name}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{e.analyst_name}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={cn("font-mono text-xs", GRADE_BADGE_CLASS[e.reliability_grade])} title={e.admiralty_code}>
                      {e.admiralty_code}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={cn("text-xs", GRADE_BADGE_CLASS[e.reliability_grade])}>
                      {e.reliability_grade}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{e.credibility_code}</TableCell>
                  <TableCell className="max-w-[200px] truncate text-xs text-muted-foreground" title={e.notes}>
                    {e.notes || "—"}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {e.last_updated || e.added_date}
                  </TableCell>
                  <TableCell>
                    {can("manage_sources") && (
                      <div className="flex gap-1">
                        <Button size="sm" variant="outline" className="h-6 px-1.5 text-xs" onClick={() => setEditEntry(e)}>
                          Edit
                        </Button>
                        <Button size="sm" variant="destructive" className="h-6 px-1.5 text-xs" onClick={() => setRemoveTarget(e)}>
                          Remove
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div className="mt-3 flex justify-center">
            <SimplePager page={page} totalPages={totalPages} totalLabel={`${total} results`} onPageChange={setPage} />
          </div>
        </>
      )}

      <SrEntryDialog key={addKey} mode="add" open={addOpen} onClose={() => setAddOpen(false)} onSaved={invalidate} />
      <SrEntryDialog
        key={editEntry?.id ?? "none"}
        mode="edit"
        entry={editEntry}
        open={editEntry !== null}
        onClose={() => setEditEntry(null)}
        onSaved={invalidate}
      />

      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title="Remove source rating"
        description={`Remove the source rating for "${removeTarget?.source_name}"?`}
        confirmLabel="Remove"
        onConfirm={() => removeTarget && void removeEntry(removeTarget.id)}
      />
    </div>
  );
}
