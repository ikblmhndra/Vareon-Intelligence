"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimplePager } from "@/components/pager";
import { PanelError, PanelLoading } from "@/components/newsroom/panel-shell";
import { epssColorClass, severityColorClass } from "@/lib/cve/format";
import { cn } from "@/lib/utils";
import type { components } from "@/lib/api/schema";
import type { PkgVulnAckResult } from "@/lib/api/loose-types";
import { VulnDetailModal } from "@/components/cve/pkgvuln/vuln-detail-modal";

const PAGE_SIZE = 20;
const ALL = "__all__";
const SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"];

/** Port sub-view Vulns (`pvLoadVulns()`+filter, `pkgvuln.js:208-450`).
 * `ecosystem` query param ada di backend tapi gak pernah dipakai UI
 * lama -- ditambahin di sini (free win, disebut di gap notes). */
export function VulnsPanel({ active }: { active: boolean }) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [severity, setSeverity] = useState("");
  const [packageName, setPackageName] = useState("");
  const [kevOnly, setKevOnly] = useState(false);
  const [unackedOnly, setUnackedOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<components["schemas"]["PackageVulnOut"] | null>(null);

  const packagesQuery = useQuery({
    queryKey: ["pkgvuln", "packages-for-filter"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pkgvuln/packages", { params: { query: { page: 1, page_size: 500 } } });
      if (error) throw error;
      return data.items.map((p) => p.name);
    },
  });

  const listQuery = useQuery({
    queryKey: ["pkgvuln", "vulns", search, severity, packageName, kevOnly, unackedOnly, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pkgvuln/vulns", {
        params: {
          query: {
            page,
            page_size: PAGE_SIZE,
            sort_by: "adjusted_score",
            sort_dir: "desc",
            search: search || undefined,
            severity: severity || undefined,
            package_name: packageName || undefined,
            kev_only: kevOnly || undefined,
            acknowledged: unackedOnly ? "false" : undefined,
          },
        },
      });
      if (error) throw error;
      return data;
    },
    enabled: active,
  });

  async function toggleAck(vulnId: number) {
    const { data, error } = await api.PATCH("/api/pkgvuln/vulns/{vuln_id}/ack", { params: { path: { vuln_id: vulnId } } });
    if (error) {
      toast.error("Acknowledge failed");
      return;
    }
    const d = data as unknown as PkgVulnAckResult;
    toast.success(d.acknowledged ? "Acknowledged." : "Un-acknowledged.");
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "vulns"] });
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "stats"] });
  }

  function resetFilters() {
    setSearch("");
    setSeverity("");
    setPackageName("");
    setKevOnly(false);
    setUnackedOnly(false);
    setPage(1);
  }

  const total = listQuery.data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-2 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Search</Label>
          <Input
            placeholder="Advisory, CVE, summary…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="w-48 font-mono text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Severity</Label>
          <Select
            items={{ [ALL]: "All Severities", ...Object.fromEntries(SEVERITIES.map((s) => [s, s])) }}
            value={severity || ALL}
            onValueChange={(v) => {
              setSeverity(v === ALL ? "" : (v ?? ""));
              setPage(1);
            }}
          >
            <SelectTrigger size="sm" className="w-36 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL} className="font-mono text-xs">
                All Severities
              </SelectItem>
              {SEVERITIES.map((s) => (
                <SelectItem key={s} value={s} className="font-mono text-xs">
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Package</Label>
          <Select
            items={{ [ALL]: "All Packages", ...Object.fromEntries((packagesQuery.data ?? []).map((p) => [p, p])) }}
            value={packageName || ALL}
            onValueChange={(v) => {
              setPackageName(v === ALL ? "" : (v ?? ""));
              setPage(1);
            }}
          >
            <SelectTrigger size="sm" className="w-40 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL} className="font-mono text-xs">
                All Packages
              </SelectItem>
              {(packagesQuery.data ?? []).map((p) => (
                <SelectItem key={p} value={p} className="font-mono text-xs">
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <label className="mb-1.5 flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
          <Checkbox
            checked={kevOnly}
            onCheckedChange={(c) => {
              setKevOnly(c === true);
              setPage(1);
            }}
          />
          KEV only
        </label>
        <label className="mb-1.5 flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
          <Checkbox
            checked={unackedOnly}
            onCheckedChange={(c) => {
              setUnackedOnly(c === true);
              setPage(1);
            }}
          />
          Unacked only
        </label>
        <Button size="sm" variant="outline" onClick={resetFilters}>
          Reset
        </Button>
      </div>

      {listQuery.isPending && <PanelLoading />}
      {listQuery.isError && <PanelError />}
      {listQuery.data && (
        <>
          <Table framed>
            <TableHeader>
              <TableRow>
                <TableHead>Advisory</TableHead>
                <TableHead>Package</TableHead>
                <TableHead>Summary</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Score</TableHead>
                <TableHead>EPSS</TableHead>
                <TableHead>Published</TableHead>
                <TableHead>Fixed In</TableHead>
                <TableHead>Ack</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {listQuery.data.items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={9} className="py-8 text-center text-xs text-muted-foreground">
                    No package vulnerabilities found.
                  </TableCell>
                </TableRow>
              )}
              {listQuery.data.items.map((v) => (
                <TableRow key={v.id} className="cursor-pointer" onClick={() => setSelected(v)}>
                  <TableCell className="font-mono text-xs">
                    {v.advisory_id}
                    {v.aliases.length > 0 && <div className="text-xs text-muted-foreground">{v.aliases.join(", ")}</div>}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {v.package_name}
                    {v.pinned_version && <span className="text-muted-foreground">@{v.pinned_version}</span>}
                  </TableCell>
                  <TableCell className="max-w-[240px] truncate text-xs">{v.summary || "—"}</TableCell>
                  <TableCell className={cn("text-xs font-semibold", severityColorClass(v.adjusted_severity || v.severity))}>
                    {v.adjusted_severity || v.severity}
                  </TableCell>
                  <TableCell className="font-mono text-xs" onClick={(e) => e.stopPropagation()}>
                    {v.adjusted_score?.toFixed(1) ?? "—"}
                    {v.kev && (
                      <Badge variant="destructive" className="ml-1 text-xs">
                        KEV
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className={cn("font-mono text-xs", v.epss_score != null ? epssColorClass(v.epss_score) : "text-muted-foreground")}>
                    {v.epss_score != null ? `${(v.epss_score * 100).toFixed(2)}%` : "—"}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{v.published?.slice(0, 10) || "—"}</TableCell>
                  <TableCell className="font-mono text-xs text-primary">{v.fixed_version || "—"}</TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <Checkbox checked={v.acknowledged} onCheckedChange={() => void toggleAck(v.id)} />
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

      <VulnDetailModal vuln={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
