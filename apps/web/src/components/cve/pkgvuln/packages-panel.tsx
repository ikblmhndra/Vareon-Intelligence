"use client";

import { useState, type ReactNode } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { FilterSelect } from "@/components/ui/filter-select";
import { NumberedPager } from "@/components/ui/numbered-pager";
import { RowMenu } from "@/components/ui/row-menu";
import { SearchInput } from "@/components/ui/search-input";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { PKG_ECOSYSTEMS } from "@/components/cve/pkgvuln/add-packages-dialog";
import { DepsModal } from "@/components/cve/pkgvuln/deps-modal";
import { EditPackageDialog } from "@/components/cve/pkgvuln/edit-package-dialog";
import type { PkgDeleteResult, PkgTaskStartedResult } from "@/lib/api/loose-types";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";
import { useDebounced } from "@/lib/cve/catalog";
import { severityChipKey } from "@/lib/cve/labels";
import { fmtCompactAge } from "@/lib/format";

type MonitoredPackageOut = components["schemas"]["MonitoredPackageOut"];

const PAGE_SIZE = 25;
const ECOSYSTEM_OPTIONS = [
  { value: "all", label: "all" },
  ...PKG_ECOSYSTEMS.map((e) => ({ value: e, label: e })),
] as const;

interface PackagesPanelProps {
  /** Pil Vulnerabilities | Packages dan tombol toolbar; dipasang oleh `PkgVulnView` supaya sama di kedua segmen. */
  segment: ReactNode;
  actions: ReactNode;
}

/** Segmen Packages (spec 2a 6.8): tabel penuh di dalam kartu utama; permukaan aksi = menu baris "...".
 * Scan/resolve-deps fire-and-forget (`BackgroundTasks`, tak ada endpoint status job): segarkan query
 * sesudah jeda tetap, bukan menunggu sinyal "selesai" yang memang tidak ada. */
export function PackagesPanel({ segment, actions }: PackagesPanelProps) {
  const can = useCan();
  const canManage = can("manage_cve");
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [ecosystem, setEcosystem] = useState<string>("all");
  const [removeTarget, setRemoveTarget] = useState<{ id: number; name: string } | null>(null);
  const [editTarget, setEditTarget] = useState<MonitoredPackageOut | null>(null);
  const [depsTarget, setDepsTarget] = useState<number | null>(null);
  const q = useDebounced(search.trim());

  const list = useQuery({
    queryKey: ["pkgvuln", "packages", q, ecosystem, page],
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pkgvuln/packages", {
        params: {
          query: {
            page,
            page_size: PAGE_SIZE,
            search: q || undefined,
            ecosystem: ecosystem === "all" ? undefined : ecosystem,
          },
        },
      });
      if (error) throw error;
      return data;
    },
  });

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "packages"] });
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "package-lookup"] });
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "stats"] });
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "vulns"] });
  }

  function invalidateSoon(ms: number) {
    invalidate();
    setTimeout(invalidate, ms);
  }

  async function removePackage(id: number) {
    const { data, error } = await api.DELETE("/api/pkgvuln/packages/{pkg_id}", { params: { path: { pkg_id: id } } });
    if (error) {
      toast.error("Delete failed");
      return;
    }
    const d = data as unknown as PkgDeleteResult;
    toast.success(`${d.deleted} removed.`);
    invalidate();
  }

  async function scanOne(id: number) {
    const { error } = await api.POST("/api/pkgvuln/packages/{pkg_id}/scan", { params: { path: { pkg_id: id } } });
    if (error) toast.error("Scan failed to start");
    else toast.success("Scan started.");
    invalidateSoon(4000);
  }

  async function resolveDeps(id: number) {
    const { data, error } = await api.POST("/api/pkgvuln/packages/{pkg_id}/resolve-deps", { params: { path: { pkg_id: id } } });
    if (error) toast.error("Resolve failed to start");
    else {
      const d = data as unknown as PkgTaskStartedResult;
      toast.success(`Resolving dependencies for ${d.package}...`);
    }
    invalidateSoon(8000);
  }

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  return (
    <Card>
      <CardContent className="flex flex-col gap-3">
        <div>{segment}</div>
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput
            value={search}
            onChange={(v) => {
              setSearch(v);
              setPage(1);
            }}
            placeholder="Search packages"
            aria-label="Search packages"
            className="w-full sm:w-64"
          />
          <FilterSelect
            prefix="Ecosystem"
            value={ecosystem}
            onChange={(v) => {
              setEcosystem(v);
              setPage(1);
            }}
            options={ECOSYSTEM_OPTIONS}
          />
          <div className="flex flex-wrap items-center gap-2 lg:ml-auto">{actions}</div>
        </div>

        {list.isPending && <Skeleton className="h-64 w-full rounded-lg" />}
        {list.isError && (
          <StatePanel
            variant="error"
            title="Could not load packages"
            action={
              <Button variant="outline" onClick={() => void list.refetch()}>
                Retry
              </Button>
            }
          />
        )}
        {list.isSuccess && items.length === 0 && (
          <StatePanel
            variant="empty"
            title="No monitored packages"
            description={q || ecosystem !== "all" ? "No package matches these filters." : "Add a package or import a lockfile to start monitoring."}
          />
        )}
        {items.length > 0 && (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Package</TableHead>
                  <TableHead>Ecosystem</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Vulnerabilities</TableHead>
                  <TableHead>Deps</TableHead>
                  <TableHead>Scorecard</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Last scan</TableHead>
                  <TableHead className="w-10">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-code text-xs font-semibold">{p.name}</TableCell>
                    <TableCell>
                      <Chip kind="flag" value={p.ecosystem} />
                    </TableCell>
                    <TableCell className="font-code text-xs">
                      {p.version || "any"}
                      {p.latest_version && p.latest_version !== p.version && (
                        <span className="text-muted-foreground"> {"->"} {p.latest_version}</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {p.vuln_count === 0 ? (
                        <Chip kind="flag" value="NONE" />
                      ) : (
                        <Chip kind="severity" value={severityChipKey(p.highest_severity)}>
                          {p.highest_severity} {p.vuln_count}
                        </Chip>
                      )}
                    </TableCell>
                    <TableCell className="text-xs">
                      {p.dep_resolved_at ? (
                        <button
                          type="button"
                          aria-label={`Dependencies of ${p.name}`}
                          onClick={() => setDepsTarget(p.id)}
                          className="rounded-sm font-semibold underline outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                        >
                          {p.dep_direct_count} + {p.dep_indirect_count}
                        </button>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs tabular-nums">{p.scorecard_score != null ? p.scorecard_score.toFixed(1) : "—"}</TableCell>
                    <TableCell className="max-w-[200px] truncate text-xs text-muted-foreground" title={p.source_path || p.source}>
                      {p.source_path || p.source}
                    </TableCell>
                    <TableCell className="text-xs">{fmtCompactAge(p.last_scan)}</TableCell>
                    <TableCell>
                      <RowMenu
                        label={`Actions for ${p.name}`}
                        items={[
                          { label: "Edit", onSelect: () => setEditTarget(p), hidden: !canManage },
                          { label: "Scan now", onSelect: () => void scanOne(p.id), hidden: !canManage },
                          { label: "Resolve deps", onSelect: () => void resolveDeps(p.id), hidden: !canManage },
                          {
                            label: "Remove",
                            onSelect: () => setRemoveTarget({ id: p.id, name: p.name }),
                            destructive: true,
                            hidden: !canManage,
                          },
                        ]}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <NumberedPager page={page} totalPages={totalPages} onPageChange={setPage} label="Packages pages" />
          </>
        )}
      </CardContent>

      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title={`Remove ${removeTarget?.name ?? "package"}`}
        description="Stop monitoring this package? Its vulnerability records will also be deleted."
        confirmLabel="Remove"
        onConfirm={() => removeTarget && void removePackage(removeTarget.id)}
      />
      <EditPackageDialog key={editTarget?.id ?? "none"} pkg={editTarget} onClose={() => setEditTarget(null)} onSaved={invalidate} />
      <DepsModal pkgId={depsTarget} onClose={() => setDepsTarget(null)} onResolved={invalidate} />
    </Card>
  );
}
