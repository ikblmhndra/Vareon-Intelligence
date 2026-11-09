"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { AddCustomTechDialog } from "@/components/cve/add-custom-tech-dialog";
import { AddFromCatalogDialog } from "@/components/cve/add-from-catalog-dialog";
import { CoverageCard } from "@/components/cve/coverage-card";
import { EditTechDialog } from "@/components/cve/edit-tech-dialog";
import { MapTechDialog } from "@/components/cve/map-tech-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FilterSelect } from "@/components/ui/filter-select";
import { LoadMoreFooter } from "@/components/ui/load-more-footer";
import { RowMenu } from "@/components/ui/row-menu";
import { SearchInput } from "@/components/ui/search-input";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { TechStackSuccessFlag } from "@/lib/api/loose-types";
import { useCan } from "@/lib/auth/permissions";
import { HOSTING_LABEL, targetLabel, useMonitorActions, type TechStackOut } from "@/lib/cve/catalog";
import { useCveView } from "@/lib/cve/view-state";
import { fmtShortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE = 25;
// Endpoint techstack tidak punya filter exposure/hosting di server: ambil sekali (maks 500 entri) lalu
// saring dan cari di klien. Stack lebih dari 500 entri butuh filter server-side.
const FETCH_ALL = 500;

const EXPOSURE_FILTER = [
  { value: "all", label: "all" },
  { value: "public", label: "public" },
  { value: "internal", label: "internal" },
  { value: "both", label: "both" },
] as const;
const HOSTING_FILTER = [
  { value: "all", label: "all" },
  { value: "on_prem", label: "on-prem" },
  { value: "cloud", label: "cloud" },
  { value: "saas", label: "SaaS" },
] as const;
const STATE_FILTER = [
  { value: "active", label: "active" },
  { value: "hidden", label: "hidden" },
  { value: "all", label: "all" },
] as const;

type ListData = { items: TechStackOut[]; total: number; page: number; page_size: number };
const LIST_KEY = ["techstack", "list", "all"] as const;

function exposureChip(value: string) {
  return value === "public" || value === "internal" || value === "both" ? (
    <Chip kind="exposure" value={value} />
  ) : (
    <Chip kind="flag" value={value} />
  );
}

/**
 * Sub-view "Monitored Tech" (spec 2a, D13-D15): toolbar (cari, filter Exposure/Hosting/State, Add custom,
 * Add from catalog), tabel entri dengan hitungan match, chip exposure, saklar state dan menu baris
 * (Edit / Targets / Remove), serta kolom kanan Coverage. Entri tanpa target katalog dicocokkan lewat teks
 * nama sampai di-map ("Map to catalog"). "Hidden" = nonaktif: keluar dari tab CVEs/dashboard/export tetapi
 * tidak dihapus (CVE, ticket, ACK tetap); "Remove" menghapus entri (CVE-nya jadi yatim), jadi dialognya
 * menawarkan "Hide instead". Aksi tulis hanya untuk `manage_cve`.
 */
export function MonitoredTechPanel() {
  const can = useCan();
  const canManage = can("manage_cve");
  const queryClient = useQueryClient();
  const actions = useMonitorActions();
  const { addFromCatalogRequested, clearAddFromCatalog } = useCveView();

  const [search, setSearch] = useState("");
  const [exposure, setExposure] = useState<(typeof EXPOSURE_FILTER)[number]["value"]>("all");
  const [hosting, setHosting] = useState<(typeof HOSTING_FILTER)[number]["value"]>("all");
  const [state, setState] = useState<(typeof STATE_FILTER)[number]["value"]>("active");
  const [limit, setLimit] = useState(PAGE);
  const [addCatalogOpen, setAddCatalogOpen] = useState(false);
  const [addCustomOpen, setAddCustomOpen] = useState(false);
  const [mapId, setMapId] = useState<number | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [removeTarget, setRemoveTarget] = useState<TechStackOut | null>(null);
  const [pendingIds, setPendingIds] = useState<ReadonlySet<number>>(new Set());

  // Empty state tab CVEs meminta picker dibuka: dialog terbuka selama bendera aktif; menutupnya membersihkan bendera.
  const catalogOpen = addCatalogOpen || (addFromCatalogRequested && canManage);
  function setCatalogOpen(open: boolean) {
    setAddCatalogOpen(open);
    if (!open) clearAddFromCatalog();
  }

  const listQuery = useQuery({
    queryKey: LIST_KEY,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/techstack", {
        params: { query: { page: 1, page_size: FETCH_ALL, sort_by: "name", sort_dir: "asc" } },
      });
      if (error) throw error;
      return data;
    },
  });

  const all = listQuery.data?.items ?? [];
  const needle = search.trim().toLowerCase();
  const rows = all.filter((t) => {
    if (state !== "all" && t.active !== (state === "active")) return false;
    if (exposure !== "all" && t.exposure !== exposure) return false;
    if (hosting !== "all" && t.hosting_type !== hosting) return false;
    if (!needle) return true;
    return [t.name, ...t.targets.map(targetLabel)].some((s) => s.toLowerCase().includes(needle));
  });
  const shown = rows.slice(0, limit);
  const mapEntry = all.find((t) => t.id === mapId) ?? null;
  const editEntry = all.find((t) => t.id === editId) ?? null;

  function refreshDependents() {
    for (const key of ["techstack", "catalog", "cve-db", "cve"]) void queryClient.invalidateQueries({ queryKey: [key] });
  }

  /** Saklar State: ubah di cache dulu, PATCH, lalu kembalikan + toast galat bila gagal. */
  async function toggleActive(t: TechStackOut, active: boolean) {
    const previous = queryClient.getQueryData<ListData>(LIST_KEY);
    queryClient.setQueryData<ListData>(LIST_KEY, (d) =>
      d ? { ...d, items: d.items.map((x) => (x.id === t.id ? { ...x, active } : x)) } : d,
    );
    setPendingIds((s) => new Set(s).add(t.id));
    const { error } = await api.PATCH("/api/techstack/{tech_id}", {
      params: { path: { tech_id: t.id } },
      body: { active },
    });
    setPendingIds((s) => {
      const n = new Set(s);
      n.delete(t.id);
      return n;
    });
    if (error) {
      queryClient.setQueryData(LIST_KEY, previous);
      toast.error(`Could not ${active ? "resume" : "hide"} ${t.name}`);
      return;
    }
    refreshDependents();
  }

  async function removeTech(t: TechStackOut) {
    const { data, error } = await api.DELETE("/api/techstack/{tech_id}", { params: { path: { tech_id: t.id } } });
    if (error || !(data as unknown as TechStackSuccessFlag | undefined)?.success) {
      toast.error(`Could not remove ${t.name}`);
      return;
    }
    toast.success(`Removed ${t.name}`);
    refreshDependents();
  }

  const unfiltered = all.length === 0;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput
            value={search}
            onChange={(v) => {
              setSearch(v);
              setLimit(PAGE);
            }}
            placeholder="Search tech"
            aria-label="Search tech"
            className="w-full sm:w-64"
          />
          <FilterSelect
            prefix="Exposure"
            value={exposure}
            onChange={(v) => {
              setExposure(v);
              setLimit(PAGE);
            }}
            options={EXPOSURE_FILTER}
          />
          <FilterSelect
            prefix="Hosting"
            value={hosting}
            onChange={(v) => {
              setHosting(v);
              setLimit(PAGE);
            }}
            options={HOSTING_FILTER}
          />
          <FilterSelect
            prefix="State"
            value={state}
            onChange={(v) => {
              setState(v);
              setLimit(PAGE);
            }}
            options={STATE_FILTER}
          />
          {canManage && (
            <div className="ml-auto flex items-center gap-2">
              <Button variant="outline" onClick={() => setAddCustomOpen(true)}>
                Add custom
              </Button>
              <Button onClick={() => setAddCatalogOpen(true)}>+ Add from catalog</Button>
            </div>
          )}
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Monitored tech</CardTitle>
            <CardDescription>
              {listQuery.data?.total ?? 0} entries - CVEs show in the CVEs tab only for active entries
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {listQuery.isPending && <Skeleton className="h-48 w-full" />}
            {listQuery.isError && (
              <StatePanel
                variant="error"
                title="Could not load monitored tech"
                action={
                  <Button variant="outline" onClick={() => void listQuery.refetch()}>
                    Retry
                  </Button>
                }
              />
            )}
            {listQuery.data && unfiltered && (
              <StatePanel
                variant="empty"
                title="No monitored tech yet"
                description="Add products from the catalog so CVEs can be matched to your stack."
              />
            )}
            {listQuery.data && !unfiltered && rows.length === 0 && (
              <StatePanel variant="empty" title="No entries match these filters" />
            )}
            {rows.length > 0 && (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Catalog match</TableHead>
                      <TableHead>Exposure</TableHead>
                      <TableHead>Hosting</TableHead>
                      <TableHead className="text-right">Matches</TableHead>
                      <TableHead>Added</TableHead>
                      <TableHead>State</TableHead>
                      <TableHead>
                        <span className="sr-only">Actions</span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {shown.map((t) => (
                      <TableRow key={t.id} className={cn(!t.active && "text-muted-foreground")}>
                        <TableCell className="font-semibold">{t.name}</TableCell>
                        <TableCell>
                          {t.targets.length === 0 ? (
                            <span className="inline-flex items-center gap-2">
                              <Chip kind="cve" value="unmapped" />
                              {canManage && (
                                <button
                                  type="button"
                                  onClick={() => setMapId(t.id)}
                                  className="rounded-sm text-xs font-semibold text-destructive-text underline outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                                >
                                  Map to catalog
                                </button>
                              )}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 text-xs">
                              {targetLabel(t.targets[0])}
                              {t.targets.length > 1 && (
                                <span className="text-muted-foreground">+{t.targets.length - 1}</span>
                              )}
                            </span>
                          )}
                        </TableCell>
                        <TableCell>{exposureChip(t.exposure)}</TableCell>
                        <TableCell className="text-xs">{HOSTING_LABEL[t.hosting_type] ?? t.hosting_type}</TableCell>
                        <TableCell className="text-right text-xs tabular-nums">{t.match_count}</TableCell>
                        <TableCell className="text-xs">{fmtShortDate(t.added_date)}</TableCell>
                        <TableCell>
                          <Switch
                            checked={t.active}
                            disabled={!canManage || pendingIds.has(t.id)}
                            onCheckedChange={(v) => void toggleActive(t, v)}
                            aria-label={`${t.active ? "Hide" : "Resume"} ${t.name}`}
                            label={<span className="text-xs">{t.active ? "active" : "hidden"}</span>}
                          />
                        </TableCell>
                        <TableCell className="text-right">
                          {canManage && (
                            <RowMenu
                              label={`Actions for ${t.name}`}
                              items={[
                                { label: "Edit", onSelect: () => setEditId(t.id) },
                                { label: "Targets", onSelect: () => setMapId(t.id), hidden: t.targets.length === 0 },
                                { label: "Remove", onSelect: () => setRemoveTarget(t), destructive: true },
                              ]}
                            />
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <LoadMoreFooter
                  shown={shown.length}
                  total={rows.length}
                  hasMore={shown.length < rows.length}
                  loading={false}
                  onLoadMore={() => setLimit((l) => l + PAGE)}
                />
              </>
            )}
            <p className="text-xs text-muted-foreground">Hidden entries keep their history but drop out of the CVEs tab.</p>
          </CardContent>
        </Card>
      </div>

      <CoverageCard />

      <AddFromCatalogDialog open={catalogOpen} onOpenChange={setCatalogOpen} />
      <AddCustomTechDialog open={addCustomOpen} onOpenChange={setAddCustomOpen} />
      <MapTechDialog entry={mapEntry} onOpenChange={(open) => !open && setMapId(null)} />
      <EditTechDialog entry={editEntry} onOpenChange={(open) => !open && setEditId(null)} />

      <Dialog open={removeTarget !== null} onOpenChange={(open) => !open && setRemoveTarget(null)}>
        <DialogContent className="sm:max-w-md">
          {removeTarget && (
            <>
              <DialogHeader>
                <DialogTitle>Remove {removeTarget.name}?</DialogTitle>
                <DialogDescription>
                  Its CVEs stay in the database but become orphaned (purge-orphaned can delete them). To only drop it from
                  the CVEs tab and keep its history, hide it instead.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="ghost" onClick={() => setRemoveTarget(null)}>
                  Cancel
                </Button>
                {removeTarget.active && (
                  <Button
                    variant="outline"
                    disabled={actions.busy}
                    onClick={() => {
                      void toggleActive(removeTarget, false);
                      setRemoveTarget(null);
                    }}
                  >
                    Hide instead
                  </Button>
                )}
                <Button
                  variant="destructive"
                  onClick={() => {
                    void removeTech(removeTarget);
                    setRemoveTarget(null);
                  }}
                >
                  Remove {removeTarget.name}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
