"use client";

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { severityChipKey } from "@/lib/cve/labels";
import { fmtShortDate } from "@/lib/format";

type PackageVulnOut = components["schemas"]["PackageVulnOut"];
export type MonitoredPackageOut = components["schemas"]["MonitoredPackageOut"];

interface VulnDetailCardProps {
  vuln: PackageVulnOut;
  canManage: boolean;
  ackBusy: boolean;
  onToggleAck: () => void;
  /** Buka `DepsModal` untuk paket ini (id dari lookup paket). */
  onOpenDeps: (pkgId: number) => void;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border py-2 text-xs last:border-b-0">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words text-right font-medium">{children}</dd>
    </div>
  );
}

function MiniStat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-lg bg-surface px-3 py-2">
      <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm font-semibold">{children}</p>
    </div>
  );
}

/** Panel rincian kerentanan paket (spec 2a 6.7), pengganti `VulnDetailModal`. Data paket (dependensi,
 * scorecard, source path) diambil dari lookup `GET /api/pkgvuln/packages?search=name&ecosystem=`. */
export function VulnDetailCard({ vuln, canManage, ackBusy, onToggleAck, onOpenDeps }: VulnDetailCardProps) {
  const lookup = useQuery({
    queryKey: ["pkgvuln", "package-lookup", vuln.package_name, vuln.ecosystem],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pkgvuln/packages", {
        params: { query: { search: vuln.package_name, ecosystem: vuln.ecosystem, page: 1, page_size: 25 } },
      });
      if (error) throw error;
      const want = vuln.package_name.toLowerCase();
      return data.items.find((p) => p.name.toLowerCase() === want) ?? null;
    },
  });
  const pkg: MonitoredPackageOut | null = lookup.data ?? null;
  const sev = vuln.adjusted_severity || vuln.severity;
  const resolved = !!pkg?.dep_resolved_at;
  const pinned = vuln.pinned_version || pkg?.version || "any";

  return (
    <Card className="lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="font-code break-all">{vuln.package_name}</CardTitle>
            <CardDescription>
              {vuln.ecosystem} - pinned {pinned} - latest {pkg?.latest_version || "—"}
            </CardDescription>
          </div>
          <Chip kind="severity" value={severityChipKey(sev)}>
            {sev}
          </Chip>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-3 gap-2">
          <MiniStat label="Direct deps">{resolved ? pkg.dep_direct_count : "—"}</MiniStat>
          <MiniStat label="Indirect">{resolved ? pkg.dep_indirect_count : "—"}</MiniStat>
          <MiniStat label="Scorecard">{pkg?.scorecard_score != null ? `${pkg.scorecard_score.toFixed(1)} / 10` : "—"}</MiniStat>
        </div>
        {!lookup.isPending && !resolved && <p className="text-xs text-muted-foreground">Not resolved yet</p>}

        <div className="flex flex-col gap-1">
          <p className="text-xs font-semibold">
            <span className="font-code">{vuln.advisory_id}</span>
            {vuln.aliases.length > 0 && <span className="font-normal text-muted-foreground"> - {vuln.aliases.join(", ")}</span>}
          </p>
          <p className="text-xs leading-relaxed text-muted-foreground">{vuln.details || vuln.summary || "No description."}</p>
        </div>

        <dl>
          <Row label="Affected">
            <span className="font-code">{vuln.affected_version_ranges.length > 0 ? vuln.affected_version_ranges.join(", ") : "—"}</span>
          </Row>
          <Row label="Fixed in">
            <span className="font-code text-success-text">{vuln.fixed_version || "—"}</span>
          </Row>
          <Row label="EPSS">
            {vuln.epss_score != null
              ? `${vuln.epss_score.toFixed(2)}${vuln.epss_percentile != null ? ` - ${Math.round(vuln.epss_percentile * 100)}th pct` : ""}`
              : "—"}
          </Row>
          <Row label="CISA KEV">{vuln.kev ? `added ${fmtShortDate(vuln.kev_date_added)}` : "Not listed"}</Row>
          <Row label="Source">{pkg?.source_path || pkg?.source || vuln.source}</Row>
          {vuln.acknowledged && (
            <Row label="Acknowledged">
              {vuln.ack_by || "—"} on {fmtShortDate(vuln.ack_date)}
            </Row>
          )}
        </dl>

        <div className="flex flex-wrap gap-2">
          {canManage && (
            <Button size="sm" variant="outline" loading={ackBusy} onClick={onToggleAck}>
              {vuln.acknowledged ? "Remove acknowledgement" : "Acknowledge"}
            </Button>
          )}
          <Button size="sm" variant="outline" disabled={!pkg} onClick={() => pkg && onOpenDeps(pkg.id)}>
            Dependency graph
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
