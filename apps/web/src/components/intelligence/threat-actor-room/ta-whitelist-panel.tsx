"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimplePager } from "@/components/pager";
import { ConfirmDialog } from "@/components/confirm-dialog";

const PAGE_SIZE = 50;
type SortField = "name" | "added_date";

/** Port bagian "WHITELIST SUB-VIEW" (`ta.js:202-363`) -- grup yang
 * di-remove dari tracking (gak bisa di-re-add lewat Tracked Groups
 * selama masih di sini), Restore ngehapus dari whitelist. */
export function TaWhitelistPanel() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortField>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(1);
  const [restoreTarget, setRestoreTarget] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["ta-room", "ta-whitelist", search, sortBy, sortDir, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/ta/whitelist", {
        params: { query: { search: search || undefined, sort_by: sortBy, sort_dir: sortDir, page, page_size: PAGE_SIZE } },
      });
      if (error) throw error;
      return data;
    },
  });

  function sortClick(field: SortField) {
    if (sortBy === field) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortBy(field);
      setSortDir("asc");
    }
    setPage(1);
  }

  async function restore(name: string) {
    try {
      const { error } = await api.DELETE("/api/ta/whitelist/{name}", { params: { path: { name } } });
      if (error) throw new Error(JSON.stringify(error));
      toast.success(`"${name}" restored.`);
      await queryClient.invalidateQueries({ queryKey: ["ta-room", "ta-whitelist"] });
      await queryClient.invalidateQueries({ queryKey: ["ta-room", "ta-groups"] });
    } catch (e) {
      toast.error(`Could not restore "${name}": ${(e as Error).message}`);
    }
  }

  const total = query.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-2 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-muted-foreground">Search</label>
          <Input
            placeholder="Actor name…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="w-48 font-mono text-xs"
          />
        </div>
        <span className="ml-auto font-mono text-[13px] text-muted-foreground">
          {total} group{total !== 1 ? "s" : ""} whitelisted
        </span>
      </div>

      {query.isPending && <p className="py-8 text-center text-xs text-muted-foreground">Loading…</p>}
      {query.isError && <p className="py-8 text-center text-xs text-destructive">Failed to load whitelist.</p>}

      {query.data && (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">#</TableHead>
                <TableHead className="cursor-pointer select-none" onClick={() => sortClick("name")}>
                  Name <span className={sortBy === "name" ? "text-primary" : "text-muted-foreground"}>{sortBy === "name" ? (sortDir === "asc" ? "↑" : "↓") : "⇅"}</span>
                </TableHead>
                <TableHead className="cursor-pointer select-none" onClick={() => sortClick("added_date")}>
                  Added Date{" "}
                  <span className={sortBy === "added_date" ? "text-primary" : "text-muted-foreground"}>{sortBy === "added_date" ? (sortDir === "asc" ? "↑" : "↓") : "⇅"}</span>
                </TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="py-6 text-center text-xs text-muted-foreground">
                    No whitelisted groups
                  </TableCell>
                </TableRow>
              )}
              {query.data.items.map((item, i) => (
                <TableRow key={item.id}>
                  <TableCell className="font-mono text-xs text-muted-foreground">{(page - 1) * PAGE_SIZE + i + 1}</TableCell>
                  <TableCell className="text-xs text-foreground">{item.name}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{item.added_date || "—"}</TableCell>
                  <TableCell className="text-right">
                    <button
                      type="button"
                      onClick={() => setRestoreTarget(item.name)}
                      className="rounded-full border border-success/35 bg-success/10 px-1.5 py-0.5 font-mono text-xs text-success-text"
                    >
                      ↩ RESTORE
                    </button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div className="mt-3 flex justify-center">
            <SimplePager page={page} totalPages={totalPages} totalLabel={`${total} total`} onPageChange={setPage} />
          </div>
        </>
      )}

      <ConfirmDialog
        open={restoreTarget !== null}
        onOpenChange={(open) => !open && setRestoreTarget(null)}
        title="Restore Threat Actor"
        description={restoreTarget ? `Restore "${restoreTarget}" to threat actor tracking?` : undefined}
        confirmLabel="↩ Restore"
        onConfirm={() => restoreTarget && void restore(restoreTarget)}
      />
    </div>
  );
}
