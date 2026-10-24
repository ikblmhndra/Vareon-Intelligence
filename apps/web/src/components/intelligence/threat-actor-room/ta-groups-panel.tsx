"use client";

import { XIcon } from "lucide-react";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimplePager } from "@/components/pager";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { cn } from "@/lib/utils";
import type { TaGroupActionResult } from "@/lib/api/loose-types";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";

type TAGroupOut = components["schemas"]["TAGroupOut"];

const PAGE_SIZE = 50;
type SortField = "name" | "added_date" | "source";

/** Port bagian "TRACKED GROUPS" (`ta.js:1-200`) -- CRUD grup TA + toggle
 * watch inline, sort klik-header (bukan `<Select>`, port apa adanya
 * karena ini tabel beneran, beda dari Watchlist yang card grid). */
export function TaGroupsPanel() {
  const can = useCan();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortField>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(1);
  const [newName, setNewName] = useState("");
  const [adding, setAdding] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<TAGroupOut | null>(null);

  const query = useQuery({
    queryKey: ["ta-room", "ta-groups", search, sortBy, sortDir, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/ta/groups", {
        params: { query: { search: search || undefined, sort_by: sortBy, sort_dir: sortDir, page, page_size: PAGE_SIZE } },
      });
      if (error) throw error;
      return data;
    },
  });

  const watchlistQuery = useQuery({
    queryKey: ["ta-room", "ta-watchlist-names"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/ta/watchlist-names");
      if (error) throw error;
      return new Set((data.names ?? []).map((n) => n.toLowerCase()));
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

  async function addGroup() {
    const name = newName.trim();
    if (!name) return;
    setAdding(true);
    try {
      const { data, error } = await api.POST("/api/ta/groups", { body: { name } });
      if (error) throw new Error(JSON.stringify(error));
      const d = data as unknown as TaGroupActionResult;
      if (d.success) {
        setNewName("");
        toast.success(`"${name}" added.`);
        setPage(1);
        await queryClient.invalidateQueries({ queryKey: ["ta-room", "ta-groups"] });
      } else {
        toast.error(`Cannot add "${name}": ${d.reason === "whitelisted" ? "group is whitelisted" : "group already exists"}`);
      }
    } catch (e) {
      toast.error(`Failed to add group: ${(e as Error).message}`);
    } finally {
      setAdding(false);
    }
  }

  async function removeGroup(g: TAGroupOut) {
    try {
      const { error } = await api.DELETE("/api/ta/groups/{group_id}", {
        params: { path: { group_id: g.id }, query: { group_name: g.name } },
      });
      if (error) throw new Error(JSON.stringify(error));
      toast.success(`"${g.name}" removed.`);
      await queryClient.invalidateQueries({ queryKey: ["ta-room", "ta-groups"] });
    } catch (e) {
      toast.error(`Failed to remove group: ${(e as Error).message}`);
    }
  }

  async function toggleWatch(name: string, watched: boolean) {
    try {
      if (watched) {
        const { error } = await api.DELETE("/api/ta/watchlist/{name}", { params: { path: { name } } });
        if (error) throw new Error(JSON.stringify(error));
        toast.success(`"${name}" removed from watchlist.`);
      } else {
        const { data, error } = await api.POST("/api/ta/watchlist", { body: { name } });
        if (error) throw new Error(JSON.stringify(error));
        const d = data as unknown as TaGroupActionResult;
        if (!d.success) {
          toast.error(`"${name}" already in watchlist.`);
          return;
        }
        toast.success(`"${name}" added to watchlist.`);
      }
      await queryClient.invalidateQueries({ queryKey: ["ta-room", "ta-watchlist-names"] });
      await queryClient.invalidateQueries({ queryKey: ["ta-room", "ta-watchlist"] });
    } catch (e) {
      toast.error(`Failed to update watchlist: ${(e as Error).message}`);
    }
  }

  const total = query.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const watchedSet = watchlistQuery.data;

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
        {can("manage_intel") && (
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-muted-foreground">Add Group</label>
          <div className="flex gap-1.5">
            <Input
              placeholder="New threat actor name…"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void addGroup()}
              className="w-56 font-mono text-xs"
            />
            <Button size="sm" disabled={adding} onClick={() => void addGroup()}>
              + Add
            </Button>
          </div>
        </div>
        )}
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          {total} group{total !== 1 ? "s" : ""} tracked
        </span>
      </div>

      {query.isPending && <p className="py-8 text-center text-xs text-muted-foreground">Loading…</p>}
      {query.isError && <p className="py-8 text-center text-xs text-destructive">Failed to load groups.</p>}

      {query.data && (
        <>
          <Table framed>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">#</TableHead>
                <SortableHead field="name" label="Name" sortBy={sortBy} sortDir={sortDir} onClick={sortClick} />
                <SortableHead field="added_date" label="Added Date" sortBy={sortBy} sortDir={sortDir} onClick={sortClick} />
                <SortableHead field="source" label="Source" sortBy={sortBy} sortDir={sortDir} onClick={sortClick} />
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.groups.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="py-6 text-center text-xs text-muted-foreground">
                    No threat actor groups found
                  </TableCell>
                </TableRow>
              )}
              {query.data.groups.map((g, i) => {
                const isWatched = watchedSet?.has(g.name.toLowerCase()) ?? false;
                return (
                  <TableRow key={g.id}>
                    <TableCell className="font-mono text-xs text-muted-foreground">{(page - 1) * PAGE_SIZE + i + 1}</TableCell>
                    <TableCell className="text-xs text-foreground">{g.name}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{g.added_date}</TableCell>
                    <TableCell>
                      <span className="rounded-full border border-border bg-background px-1.5 py-0.5 font-mono text-xs text-muted-foreground">{g.source}</span>
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap">
                      {can("manage_pir") && (
                      <button
                        type="button"
                        onClick={() => void toggleWatch(g.name, isWatched)}
                        className={cn(
                          "mr-1.5 min-h-6 rounded-full border px-1.5 py-0.5 font-mono text-xs",
                          isWatched ? "border-primary/30 bg-primary/10 text-primary-text" : "border-border text-muted-foreground",
                        )}
                      >
                        {isWatched ? "◎ UNWATCH" : "⊕ WATCH"}
                      </button>
                      )}
                      {can("manage_intel") && (
                      <button
                        type="button"
                        onClick={() => setRemoveTarget(g)}
                        className="min-h-6 rounded-full border border-destructive/35 bg-destructive/10 px-1.5 py-0.5 font-mono text-xs text-destructive-text"
                      >
                        <XIcon aria-hidden /> REMOVE
                      </button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          <div className="mt-3 flex justify-center">
            <SimplePager page={page} totalPages={totalPages} totalLabel={`${total} total`} onPageChange={setPage} />
          </div>
        </>
      )}

      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title="Remove Threat Actor"
        description={removeTarget ? `Remove "${removeTarget.name}" from threat actor tracking?` : undefined}
        warning="This group will be whitelisted and cannot be re-added."
        confirmLabel="Remove"
        onConfirm={() => removeTarget && void removeGroup(removeTarget)}
      />
    </div>
  );
}

function SortableHead({
  field,
  label,
  sortBy,
  sortDir,
  onClick,
}: {
  field: SortField;
  label: string;
  sortBy: SortField;
  sortDir: "asc" | "desc";
  onClick: (field: SortField) => void;
}) {
  const active = sortBy === field;
  return (
    <TableHead className="cursor-pointer select-none" onClick={() => onClick(field)}>
      {label} <span className={active ? "text-primary" : "text-muted-foreground"}>{active ? (sortDir === "asc" ? "↑" : "↓") : "⇅"}</span>
    </TableHead>
  );
}
