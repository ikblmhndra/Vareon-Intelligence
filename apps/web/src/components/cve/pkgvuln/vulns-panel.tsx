"use client";

import { useState, type ReactNode } from "react";
import { keepPreviousData, useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { FilterSelect } from "@/components/ui/filter-select";
import { LoadMoreFooter } from "@/components/ui/load-more-footer";
import { MasterDetail } from "@/components/ui/master-detail";
import { SearchInput } from "@/components/ui/search-input";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { StatTile } from "@/components/ui/stat-tile";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PKG_ECOSYSTEMS } from "@/components/cve/pkgvuln/add-packages-dialog";
import { DepsModal } from "@/components/cve/pkgvuln/deps-modal";
import { VulnDetailCard } from "@/components/cve/pkgvuln/vuln-detail-card";
import type { PkgVulnAckResult } from "@/lib/api/loose-types";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";
import { useDebounced } from "@/lib/cve/catalog";
import { severityChipKey } from "@/lib/cve/labels";
import { cn } from "@/lib/utils";

type PackageVulnOut = components["schemas"]["PackageVulnOut"];
type PkgVulnStats = components["schemas"]["PkgVulnStats"];

const PAGE_SIZE = 25;

const ECOSYSTEM_OPTIONS = [
  { value: "all", label: "all" },
  ...PKG_ECOSYSTEMS.map((e) => ({ value: e, label: e })),
] as const;
const SEVERITY_OPTIONS = [
  { value: "all", label: "all" },
  ...["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"].map((s) => ({ value: s, label: s.toLowerCase() })),
] as const;
const SHOW_OPTIONS = [
  { value: "unacknowledged", label: "unacknowledged" },
  { value: "acknowledged", label: "acknowledged" },
  { value: "all", label: "all" },
] as const;
export type Show = (typeof SHOW_OPTIONS)[number]["value"];

/** Filter segmen Vulnerabilities; state-nya dipegang `PkgVulnView` supaya tidak reset saat pindah segmen. */
export interface VulnFilters {
  search: string;
  ecosystem: string;
  severity: string;
  show: Show;
  packageName: string;
  kevOnly: boolean;
}
export const INITIAL_VULN_FILTERS: VulnFilters = {
  search: "",
  ecosystem: "all",
  severity: "all",
  show: "unacknowledged",
  packageName: "all",
  kevOnly: false,
};

interface VulnsPanelProps {
  filters: VulnFilters;
  onFilters: (patch: Partial<VulnFilters>) => void;
  stats: PkgVulnStats | undefined;
  /** Pil Vulnerabilities | Packages dan tombol toolbar; dipasang oleh `PkgVulnView` supaya sama di kedua segmen. */
  segment: ReactNode;
  actions: ReactNode;
}

/** Segmen Vulnerabilities (spec 2a 6.7): kartu utama berisi pil + filter + aksi, enam `StatTile`, lalu
 * master-detail (daftar urut skor yang disesuaikan, panel rincian). Aksi paket per baris ada di segmen Packages. */
export function VulnsPanel({ filters, onFilters, stats, segment, actions }: VulnsPanelProps) {
  const can = useCan();
  const canManage = can("manage_cve");
  const queryClient = useQueryClient();
  const { search, ecosystem, severity, show, packageName, kevOnly } = filters;
  const [picked, setPicked] = useState<number | null>(null);
  const [depsTarget, setDepsTarget] = useState<number | null>(null);
  const [ackBusy, setAckBusy] = useState<number | null>(null);
  const q = useDebounced(search.trim());

  // Pencarian backend hanya mencocokkan advisory/ringkasan/alias, jadi nama paket difilter lewat dropdown ini.
  const packagesQuery = useQuery({
    queryKey: ["pkgvuln", "packages-for-filter"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pkgvuln/packages", { params: { query: { page: 1, page_size: 500 } } });
      if (error) throw error;
      return data.items.map((p) => p.name);
    },
  });
  const packageOptions = [
    { value: "all", label: "all" },
    ...[...new Set(packagesQuery.data ?? [])].map((n) => ({ value: n, label: n })),
  ];

  const list = useInfiniteQuery({
    queryKey: ["pkgvuln", "vulns", q, ecosystem, severity, show, packageName, kevOnly],
    initialPageParam: 1,
    placeholderData: keepPreviousData,
    queryFn: async ({ pageParam }) => {
      const { data, error } = await api.GET("/api/pkgvuln/vulns", {
        params: {
          query: {
            page: pageParam,
            page_size: PAGE_SIZE,
            sort_by: "adjusted_score",
            sort_dir: "desc",
            search: q || undefined,
            ecosystem: ecosystem === "all" ? undefined : ecosystem,
            severity: severity === "all" ? undefined : severity,
            package_name: packageName === "all" ? undefined : packageName,
            kev_only: kevOnly || undefined,
            acknowledged: show === "all" ? undefined : show === "acknowledged" ? "true" : "false",
          },
        },
      });
      if (error) throw error;
      return data;
    },
    getNextPageParam: (last, all) => (all.reduce((n, p) => n + p.items.length, 0) < last.total ? last.page + 1 : undefined),
  });

  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  const total = list.data?.pages[0]?.total ?? 0;
  const selected = items.find((v) => v.id === picked) ?? items[0] ?? null;

  async function toggleAck(vulnId: number) {
    setAckBusy(vulnId);
    const { data, error } = await api.PATCH("/api/pkgvuln/vulns/{vuln_id}/ack", { params: { path: { vuln_id: vulnId } } });
    setAckBusy(null);
    if (error) {
      toast.error("Acknowledge failed");
      return;
    }
    const d = data as unknown as PkgVulnAckResult;
    toast.success(d.acknowledged ? "Acknowledged." : "Un-acknowledged.");
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "vulns"] });
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "stats"] });
  }

  function invalidatePackages() {
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "packages"] });
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "package-lookup"] });
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "stats"] });
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "vulns"] });
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardContent className="flex flex-col gap-3">
          <div>{segment}</div>
          <div className="flex flex-wrap items-center gap-2">
            <SearchInput
              value={search}
              onChange={(v) => onFilters({ search: v })}
              placeholder="Search advisory or summary"
              aria-label="Search advisory or summary"
              className="w-full sm:w-64"
            />
            <FilterSelect prefix="Ecosystem" value={ecosystem} onChange={(v) => onFilters({ ecosystem: v })} options={ECOSYSTEM_OPTIONS} />
            <FilterSelect prefix="Package" value={packageName} onChange={(v) => onFilters({ packageName: v })} options={packageOptions} />
            <FilterSelect prefix="Severity" value={severity} onChange={(v) => onFilters({ severity: v })} options={SEVERITY_OPTIONS} />
            <FilterSelect prefix="Show" value={show} onChange={(v) => onFilters({ show: v })} options={SHOW_OPTIONS} />
            <Switch checked={kevOnly} onCheckedChange={(c) => onFilters({ kevOnly: c })} aria-label="KEV only" label={<span className="text-xs">KEV only</span>} />
            <div className="flex flex-wrap items-center gap-2 lg:ml-auto">{actions}</div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <StatTile label="Packages" value={stats?.packages ?? "—"} />
        <StatTile label="Vulnerable" value={stats?.vulnerable_packages ?? "—"} tone="warning" />
        <StatTile label="Critical" value={stats?.critical ?? "—"} tone="destructive" />
        <StatTile label="High" value={stats?.high ?? "—"} tone="warning" />
        <StatTile label="KEV" value={stats?.kev_count ?? "—"} tone="destructive" />
        <StatTile label="Acknowledged" value={stats ? stats.total_vulns - stats.unacknowledged : "—"} tone="success" />
      </div>

      <MasterDetail
        list={
          <Card>
            <CardHeader>
              <CardTitle>Vulnerabilities</CardTitle>
              <CardDescription>Sorted by adjusted score</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {list.isPending && <Skeleton className="h-64 w-full rounded-lg" />}
              {list.isError && (
                <StatePanel
                  variant="error"
                  title="Could not load package vulnerabilities"
                  action={
                    <Button variant="outline" onClick={() => void list.refetch()}>
                      Retry
                    </Button>
                  }
                />
              )}
              {list.isSuccess && items.length === 0 && (
                <StatePanel variant="empty" title="No package vulnerabilities found" description="Try another filter, or set Show to all." />
              )}
              {items.length > 0 && (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Advisory</TableHead>
                        <TableHead>Package</TableHead>
                        <TableHead>Severity</TableHead>
                        <TableHead className="text-right">Score</TableHead>
                        <TableHead>KEV</TableHead>
                        <TableHead>Fixed in</TableHead>
                        <TableHead className="text-right">EPSS</TableHead>
                        <TableHead>Ack</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {items.map((v) => (
                        <VulnRow
                          key={v.id}
                          vuln={v}
                          selected={v.id === selected?.id}
                          canManage={canManage}
                          busy={ackBusy === v.id}
                          onSelect={() => setPicked(v.id)}
                          onAck={() => void toggleAck(v.id)}
                        />
                      ))}
                    </TableBody>
                  </Table>
                  <LoadMoreFooter
                    shown={items.length}
                    total={total}
                    hasMore={!!list.hasNextPage}
                    loading={list.isFetchingNextPage}
                    onLoadMore={() => void list.fetchNextPage()}
                  />
                </>
              )}
            </CardContent>
          </Card>
        }
        detail={
          selected ? (
            <VulnDetailCard
              key={selected.id}
              vuln={selected}
              canManage={canManage}
              ackBusy={ackBusy === selected.id}
              onToggleAck={() => void toggleAck(selected.id)}
              onOpenDeps={setDepsTarget}
            />
          ) : list.isPending ? (
            <Skeleton className="h-64 rounded-lg" />
          ) : (
            <StatePanel variant="empty" title="No vulnerability selected" description="Pick a row to see its advisory and package." />
          )
        }
      />

      <DepsModal pkgId={depsTarget} onClose={() => setDepsTarget(null)} onResolved={invalidatePackages} />
    </div>
  );
}

function VulnRow({
  vuln: v,
  selected,
  canManage,
  busy,
  onSelect,
  onAck,
}: {
  vuln: PackageVulnOut;
  selected: boolean;
  canManage: boolean;
  busy: boolean;
  onSelect: () => void;
  onAck: () => void;
}) {
  const sev = v.adjusted_severity || v.severity;
  return (
    <TableRow selected={selected}>
      <TableCell>
        <button
          type="button"
          aria-current={selected ? "true" : undefined}
          onClick={onSelect}
          className="rounded-sm text-left font-code text-xs font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          {v.advisory_id}
        </button>
      </TableCell>
      <TableCell className="text-xs">
        <span className="font-semibold">{v.package_name}</span>
        {v.pinned_version && <span className="text-muted-foreground"> {v.pinned_version}</span>}
      </TableCell>
      <TableCell>
        <Chip kind="severity" value={severityChipKey(sev)}>
          {sev}
        </Chip>
      </TableCell>
      <TableCell className="text-right text-xs tabular-nums">{v.adjusted_score?.toFixed(1) ?? "—"}</TableCell>
      <TableCell>{v.kev && <Chip kind="cve" value="kev" />}</TableCell>
      <TableCell className={cn("font-code text-xs", v.fixed_version ? "text-success-text" : "text-muted-foreground")}>
        {v.fixed_version || "—"}
      </TableCell>
      <TableCell className="text-right text-xs tabular-nums">{v.epss_score != null ? v.epss_score.toFixed(2) : "—"}</TableCell>
      <TableCell className="text-xs">
        {v.acknowledged ? (
          <span className="text-muted-foreground">{v.ack_by || "Acked"}</span>
        ) : canManage ? (
          <button
            type="button"
            disabled={busy}
            onClick={onAck}
            aria-label={`Acknowledge ${v.advisory_id} on ${v.package_name}`}
            className="rounded-sm font-semibold underline outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:text-muted-foreground"
          >
            Ack
          </button>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </TableCell>
    </TableRow>
  );
}
