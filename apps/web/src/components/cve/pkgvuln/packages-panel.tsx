"use client";

import { LinkIcon, PencilIcon, RefreshCwIcon, XIcon } from "lucide-react";
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
import { PanelError, PanelLoading } from "@/components/newsroom/panel-shell";
import { ConfirmDialog } from "@/components/confirm-dialog";
import type { components } from "@/lib/api/schema";
import type { PkgAddResult, PkgDeleteResult, PkgTaskStartedResult } from "@/lib/api/loose-types";
import { EditPackageDialog } from "@/components/cve/pkgvuln/edit-package-dialog";
import { DepsModal } from "@/components/cve/pkgvuln/deps-modal";
import { LockfileImportDialog } from "@/components/cve/pkgvuln/lockfile-import-dialog";

const PAGE_SIZE = 20;
const ECOSYSTEMS = ["npm", "PyPI", "Go", "Maven", "crates.io", "NuGet", "RubyGems", "Packagist", "Hex"];

/** Port sub-view Packages (`pvLoadPackages()`+aksi row, `pkgvuln.js`).
 * Scan/resolve-deps/import-lockfile semua fire-and-forget
 * (`BackgroundTasks`, gak ada job-status endpoint) -- port pola legacy:
 * invalidate query abis delay tetap, bukan nunggu sinyal "selesai" yang
 * emang gak ada. */
export function PackagesPanel({ active }: { active: boolean }) {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [name, setName] = useState("");
  const [version, setVersion] = useState("");
  const [ecosystem, setEcosystem] = useState("npm");
  const [adding, setAdding] = useState(false);
  const [scanning, setScanning] = useState<number | "all" | null>(null);
  const [resolving, setResolving] = useState<number | null>(null);
  const [removeTarget, setRemoveTarget] = useState<{ id: number; name: string } | null>(null);
  const [editTarget, setEditTarget] = useState<components["schemas"]["MonitoredPackageOut"] | null>(null);
  const [depsTarget, setDepsTarget] = useState<number | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  const listQuery = useQuery({
    queryKey: ["pkgvuln", "packages", page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pkgvuln/packages", { params: { query: { page, page_size: PAGE_SIZE } } });
      if (error) throw error;
      return data;
    },
    enabled: active,
  });

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "packages"] });
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "stats"] });
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "vulns"] });
  }

  function invalidateSoon(ms: number) {
    invalidate();
    setTimeout(invalidate, ms);
  }

  async function addPackage() {
    if (!name.trim()) return;
    setAdding(true);
    try {
      const { data, error } = await api.POST("/api/pkgvuln/packages", {
        body: { name: name.trim(), ecosystem, version: version.trim() || undefined },
      });
      if (error) throw error;
      const d = data as unknown as PkgAddResult;
      if (!d.success) {
        toast.error("Add failed");
        return;
      }
      setName("");
      setVersion("");
      invalidateSoon(4000);
    } catch {
      toast.error(`${name} already exists, or not found on ${ecosystem} registry`);
    } finally {
      setAdding(false);
    }
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
    setScanning(id);
    const { error } = await api.POST("/api/pkgvuln/packages/{pkg_id}/scan", { params: { path: { pkg_id: id } } });
    if (error) toast.error("Scan failed to start");
    else toast.success("Scan started.");
    invalidateSoon(4000);
    setScanning(null);
  }

  async function scanAll() {
    setScanning("all");
    const { error } = await api.POST("/api/pkgvuln/scan");
    if (error) toast.error("Scan failed to start");
    else toast.success("Scanning all packages…");
    invalidateSoon(30000);
    setScanning(null);
  }

  async function resolveDeps(id: number) {
    setResolving(id);
    const { data, error } = await api.POST("/api/pkgvuln/packages/{pkg_id}/resolve-deps", { params: { path: { pkg_id: id } } });
    if (error) toast.error("Resolve failed to start");
    else {
      const d = data as unknown as PkgTaskStartedResult;
      toast.success(`Resolving dependencies for ${d.package}…`);
    }
    invalidateSoon(8000);
    setResolving(null);
  }

  const total = listQuery.data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-2 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Name</Label>
          <Input placeholder="e.g. lodash" value={name} onChange={(e) => setName(e.target.value)} className="w-40 font-mono text-xs" />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Version</Label>
          <Input placeholder="optional" value={version} onChange={(e) => setVersion(e.target.value)} className="w-28 font-mono text-xs" />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Ecosystem</Label>
          <Select value={ecosystem} onValueChange={(v) => v && setEcosystem(v)}>
            <SelectTrigger size="sm" className="w-32 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ECOSYSTEMS.map((e) => (
                <SelectItem key={e} value={e} className="font-mono text-xs">
                  {e}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button size="sm" disabled={!name.trim() || adding} onClick={() => void addPackage()}>
          + Add Package
        </Button>
        <Button size="sm" variant="outline" onClick={() => setImportOpen(true)}>
          ⬆ Import Lockfile
        </Button>
        <Button size="sm" variant="outline" disabled={scanning !== null} onClick={() => void scanAll()}>
          {scanning === "all" ? "Scanning…" : "Scan All"}
        </Button>
      </div>

      {listQuery.isPending && <PanelLoading />}
      {listQuery.isError && <PanelError />}
      {listQuery.data && (
        <>
          <Table framed>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Ecosystem</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Vulns</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Deps</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Last Scan</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {listQuery.data.items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={9} className="py-8 text-center text-xs text-muted-foreground">
                    No monitored packages.
                  </TableCell>
                </TableRow>
              )}
              {listQuery.data.items.map((p) => (
                <TableRow key={p.id}>
                  <TableCell className="font-mono text-xs">{p.name}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-xs">
                      {p.ecosystem}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {p.version || "any"}
                    {p.latest_version && p.latest_version !== p.version && (
                      <span className="ml-1 text-xs text-primary">→ {p.latest_version}</span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {p.critical_count > 0 && <span className="text-destructive">C{p.critical_count} </span>}
                    {p.high_count > 0 && <span className="text-warning">H{p.high_count} </span>}
                    {p.medium_count > 0 && <span className="text-primary">M{p.medium_count} </span>}
                    {p.low_count > 0 && <span className="text-muted-foreground">L{p.low_count}</span>}
                    {p.vuln_count === 0 && <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="text-xs">{p.highest_severity}</TableCell>
                  <TableCell className="text-xs">
                    {p.dep_resolved_at ? (
                      <button className="text-primary underline-offset-2 hover:underline" onClick={() => setDepsTarget(p.id)}>
                        {p.dep_direct_count}+{p.dep_indirect_count}
                        {p.scorecard_score != null ? ` · ${p.scorecard_score.toFixed(1)}` : ""}
                      </button>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-xs">
                      {p.source}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{p.last_scan?.slice(0, 10) || "—"}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <Button size="sm" variant="outline" className="h-6 px-1.5 text-xs" onClick={() => setEditTarget(p)}>
                        <PencilIcon aria-hidden />
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-6 px-1.5 text-xs"
                        disabled={scanning === p.id}
                        onClick={() => void scanOne(p.id)}
                      >
                        <RefreshCwIcon aria-hidden />
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-6 px-1.5 text-xs"
                        disabled={resolving === p.id}
                        onClick={() => void resolveDeps(p.id)}
                      >
                        <LinkIcon aria-hidden />
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        className="h-6 px-1.5 text-xs"
                        onClick={() => setRemoveTarget({ id: p.id, name: p.name })}
                      >
                        <XIcon aria-hidden />
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

      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title="Remove package"
        description={`Stop monitoring "${removeTarget?.name}"? Its vulnerability records will also be deleted.`}
        confirmLabel="Remove"
        onConfirm={() => removeTarget && void removePackage(removeTarget.id)}
      />
      <EditPackageDialog key={editTarget?.id ?? "none"} pkg={editTarget} onClose={() => setEditTarget(null)} onSaved={invalidate} />
      <DepsModal pkgId={depsTarget} onClose={() => setDepsTarget(null)} onResolved={invalidate} />
      <LockfileImportDialog open={importOpen} onOpenChange={setImportOpen} onImported={() => invalidateSoon(5000)} />
    </div>
  );
}
