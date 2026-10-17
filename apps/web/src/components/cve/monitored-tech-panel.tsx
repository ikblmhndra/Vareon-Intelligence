"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimplePager, usePageResetOn } from "@/components/pager";
import { PanelError, PanelLoading } from "@/components/newsroom/panel-shell";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { MapTechDialog } from "@/components/cve/map-tech-dialog";
import type { TechStackActionResult, TechStackSuccessFlag } from "@/lib/api/loose-types";
import { targetLabel, useDebounced, useMonitorActions } from "@/lib/cve/catalog";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;
const EXPOSURES = ["internal", "public", "both"];
const HOSTINGS = ["on_prem", "cloud", "saas"];
const STATUSES = [
  { id: "all", label: "All" },
  { id: "active", label: "Active" },
  { id: "inactive", label: "Paused" },
] as const;
type Status = (typeof STATUSES)[number]["id"];

function selectClass() {
  return "h-6 rounded border border-input bg-transparent px-1.5 font-mono text-xs outline-none";
}

/**
 * Tab "Monitored Tech" (ROADMAP #19): daftar tech yang dipantau client ini, dengan target katalog
 * tiap entri. Entri LAMA/custom tanpa target ditandai "Unmapped" (dicocokkan lewat teks nama) dan
 * punya tombol "Map to catalog" -- pemetaan 34 entri produksi dilakukan dari sini. "Pause" =
 * nonaktif: disembunyikan dari tab CVEs/dashboard/export dan tidak dicocokkan lagi, tetapi
 * TIDAK dihapus (CVE, ticket, ACK tetap); "Resume" mengembalikannya. "Remove" menghapus entri
 * (baris CVE-nya jadi yatim), jadi dialognya menawarkan Pause sebagai gantinya.
 */
export function MonitoredTechPanel() {
  const queryClient = useQueryClient();
  const actions = useMonitorActions();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<Status>("all");
  const debouncedSearch = useDebounced(search);
  const [page, setPage] = usePageResetOn(`${debouncedSearch}|${status}`);
  const [name, setName] = useState("");
  const [exposure, setExposure] = useState("internal");
  const [hosting, setHosting] = useState("on_prem");
  const [adding, setAdding] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<{ id: number; name: string } | null>(null);
  const [mapId, setMapId] = useState<number | null>(null);

  const listQuery = useQuery({
    queryKey: ["techstack", "list", debouncedSearch, status, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/techstack", {
        params: {
          query: {
            page,
            page_size: PAGE_SIZE,
            sort_by: "name",
            sort_dir: "asc",
            search: debouncedSearch || undefined,
            active: status === "all" ? undefined : status === "active",
          },
        },
      });
      if (error) throw error;
      return data;
    },
  });

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["techstack"] });
    void queryClient.invalidateQueries({ queryKey: ["catalog"] });
    void queryClient.invalidateQueries({ queryKey: ["cve"] });
  }

  async function addCustom() {
    if (!name.trim()) return;
    setAdding(true);
    try {
      const { data, error } = await api.POST("/api/techstack", {
        body: { name: name.trim(), exposure, hosting_type: hosting },
      });
      if (error) throw new Error(JSON.stringify(error));
      const d = data as unknown as TechStackActionResult;
      if (!d.success) {
        toast.error(d.reason || `${name} already exists`);
        return;
      }
      setName("");
      invalidate();
      toast.success("Added as custom (unmapped). Use “Map to catalog” for accurate matching.");
    } catch (e) {
      toast.error(`Add failed: ${(e as Error).message}`);
    } finally {
      setAdding(false);
    }
  }

  async function removeTech(id: number) {
    const { data, error } = await api.DELETE("/api/techstack/{tech_id}", { params: { path: { tech_id: id } } });
    if (error) {
      toast.error("Remove failed");
      return;
    }
    const d = data as unknown as TechStackSuccessFlag;
    if (d.success) toast.success("Removed.");
    invalidate();
  }

  async function changeExposure(id: number, value: string) {
    const { error } = await api.PATCH("/api/techstack/{tech_id}/exposure", {
      params: { path: { tech_id: id } },
      body: { exposure: value },
    });
    if (error) toast.error("Exposure update failed");
    invalidate();
  }

  async function changeHosting(id: number, value: string) {
    const { error } = await api.PATCH("/api/techstack/{tech_id}/hosting", {
      params: { path: { tech_id: id } },
      body: { hosting_type: value },
    });
    if (error) toast.error("Hosting update failed");
    invalidate();
  }

  const total = listQuery.data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;
  const unmapped = listQuery.data?.items.filter((t) => t.kind === "custom").length ?? 0;
  const mapEntry = listQuery.data?.items.find((t) => t.id === mapId) ?? null;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-2 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Search</Label>
          <Input
            placeholder="Tech name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-44 font-mono text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Status</Label>
          <select value={status} onChange={(e) => setStatus(e.target.value as Status)} className={selectClass()}>
            {STATUSES.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <div className="ml-auto flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <Label className="text-sm font-medium text-muted-foreground">Add custom (unmapped)</Label>
            <Input
              placeholder="e.g. WordPress"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-44 font-mono text-xs"
            />
          </div>
          <select value={exposure} onChange={(e) => setExposure(e.target.value)} className={selectClass()} aria-label="Exposure">
            {EXPOSURES.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
          <select value={hosting} onChange={(e) => setHosting(e.target.value)} className={selectClass()} aria-label="Hosting">
            {HOSTINGS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
          <Button size="sm" disabled={!name.trim() || adding} onClick={() => void addCustom()}>
            + Add
          </Button>
        </div>
      </div>

      {unmapped > 0 && (
        <p className="mb-3 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning-text">
          {unmapped} entr{unmapped === 1 ? "y is" : "ies are"} matched by name text only (“Unmapped”). Use “Map to catalog” so CVEs are
          matched by the product&apos;s identity instead — fewer misses and fewer false positives.
        </p>
      )}

      {listQuery.isPending && <PanelLoading />}
      {listQuery.isError && <PanelError />}
      {listQuery.data && (
        <>
          <Table framed>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Matches</TableHead>
                <TableHead>Added</TableHead>
                <TableHead>Exposure</TableHead>
                <TableHead>Hosting</TableHead>
                <TableHead>State</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {listQuery.data.items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="py-8 text-center text-xs text-muted-foreground">
                    No tech stack entries.
                  </TableCell>
                </TableRow>
              )}
              {listQuery.data.items.map((t) => (
                <TableRow key={t.id} className={cn(!t.active && "opacity-60")}>
                  <TableCell className="font-mono text-xs">{t.name}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-1">
                      {t.targets.length === 0 ? (
                        <Badge variant="outline" className="border-warning/50 text-xs text-warning">
                          Unmapped · name text
                        </Badge>
                      ) : (
                        t.targets.map((tg) => (
                          <Badge key={tg.id} variant="secondary" className="text-xs">
                            {targetLabel(tg)}
                          </Badge>
                        ))
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-[13px] text-muted-foreground">{t.added_date?.slice(0, 10) || "—"}</TableCell>
                  <TableCell>
                    <select
                      value={t.exposure}
                      onChange={(e) => void changeExposure(t.id, e.target.value)}
                      className={selectClass()}
                    >
                      {EXPOSURES.map((v) => (
                        <option key={v} value={v}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </TableCell>
                  <TableCell>
                    <select
                      value={t.hosting_type}
                      onChange={(e) => void changeHosting(t.id, e.target.value)}
                      className={selectClass()}
                    >
                      {HOSTINGS.map((v) => (
                        <option key={v} value={v}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </TableCell>
                  <TableCell>
                    <Badge variant={t.active ? "default" : "outline"} className="text-xs">
                      {t.active ? "Active" : "Paused"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1.5">
                      <Button size="sm" variant="outline" onClick={() => setMapId(t.id)}>
                        {t.targets.length === 0 ? "Map to catalog" : "Targets"}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={actions.busy}
                        onClick={() => void actions.setActive(t.id, !t.active)}
                      >
                        {t.active ? "Pause" : "Resume"}
                      </Button>
                      <Button size="sm" variant="destructive" onClick={() => setRemoveTarget({ id: t.id, name: t.name })}>
                        Remove
                      </Button>
                    </div>
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

      <MapTechDialog entry={mapEntry} onOpenChange={(open) => !open && setMapId(null)} />

      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title="Remove tech stack entry"
        description={`Remove "${removeTarget?.name}" from the tech stack?`}
        warning="Its CVEs stay in the database but become orphaned (purge-orphaned can delete them). To only hide them, use Pause instead."
        confirmLabel="Remove"
        onConfirm={() => removeTarget && void removeTech(removeTarget.id)}
      />
    </div>
  );
}
