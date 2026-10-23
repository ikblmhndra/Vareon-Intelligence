"use client";

import { LinkIcon } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

interface DepEntry {
  name: string;
  version: string;
  system: string;
}
interface ScorecardCheck {
  name: string;
  score: number | null;
  reason: string;
}

interface DepsModalProps {
  pkgId: number | null;
  onClose: () => void;
  onResolved: () => void;
}

/** Port `pvShowDeps()`/`pvDepSwitchTab()`/`pvResolveDepsFromModal()`
 * (`pkgvuln.js:678-840`). `direct_deps`/`indirect_deps`/`scorecard_checks`
 * disimpen JSONB dict polos di backend -- shape dicek langsung dari
 * `_fetch_depsdev_deps()`/`_fetch_depsdev_scorecard()`
 * (`services/pkg_vuln.py:330-416`): `{name,version,system}` /
 * `{name,score,reason}`. */
export function DepsModal({ pkgId, onClose, onResolved }: DepsModalProps) {
  const [tab, setTab] = useState<"deps" | "scorecard">("deps");
  const [rescanning, setRescanning] = useState(false);

  const depsQuery = useQuery({
    queryKey: ["pkgvuln", "deps", pkgId],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pkgvuln/packages/{pkg_id}/deps", { params: { path: { pkg_id: pkgId! } } });
      if (error) throw error;
      return data;
    },
    enabled: pkgId !== null,
  });

  async function rescan(scanTransitive: boolean) {
    if (!pkgId) return;
    setRescanning(true);
    const { error } = await api.POST("/api/pkgvuln/packages/{pkg_id}/resolve-deps", {
      params: { path: { pkg_id: pkgId }, query: { scan_transitive: scanTransitive } },
    });
    if (error) toast.error("Resolve failed to start");
    else toast.success("Re-resolving dependencies…");
    onResolved();
    setRescanning(false);
    onClose();
  }

  const d = depsQuery.data;
  const direct = (d?.direct_deps ?? []) as unknown as DepEntry[];
  const indirect = (d?.indirect_deps ?? []) as unknown as DepEntry[];
  const checks = (d?.scorecard_checks ?? []) as unknown as ScorecardCheck[];

  return (
    <Dialog open={pkgId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[80vh] w-full max-w-lg overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-mono">{d?.package_name ?? "Dependencies"}</DialogTitle>
        </DialogHeader>

        {depsQuery.isPending && <div className="py-8 text-center text-xs text-muted-foreground">Loading…</div>}
        {depsQuery.isError && (
          <div className="py-8 text-center text-xs text-destructive">No dependency graph found — resolve first.</div>
        )}
        {d && (
          <>
            {d.error && <p className="mb-2 text-xs text-destructive">{d.error}</p>}
            <div className="mb-3 flex gap-2">
              <Button size="sm" variant={tab === "deps" ? "default" : "outline"} onClick={() => setTab("deps")}>
                Dependencies ({d.total_count})
              </Button>
              <Button size="sm" variant={tab === "scorecard" ? "default" : "outline"} onClick={() => setTab("scorecard")}>
                Scorecard {d.scorecard_score != null ? d.scorecard_score.toFixed(1) : ""}
              </Button>
            </div>

            {tab === "deps" ? (
              <div className="space-y-3">
                <div>
                  <div className="mb-1 text-sm font-medium text-muted-foreground">Direct ({direct.length})</div>
                  <div className="flex flex-wrap gap-1.5">
                    {direct.map((dep, i) => (
                      <Badge key={i} variant="outline" className="font-mono text-xs">
                        {dep.name}@{dep.version}
                      </Badge>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="mb-1 text-sm font-medium text-muted-foreground">
                    Indirect ({indirect.length})
                  </div>
                  <div className="flex max-h-48 flex-wrap gap-1.5 overflow-y-auto">
                    {indirect.map((dep, i) => (
                      <Badge key={i} variant="outline" className="font-mono text-xs opacity-75">
                        {dep.name}@{dep.version}
                      </Badge>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                {d.scorecard_score == null ? (
                  <p className="text-xs text-muted-foreground">No OSSF Scorecard data available for this package.</p>
                ) : (
                  <>
                    <p className="font-mono text-xs text-muted-foreground">
                      {d.scorecard_project} · {d.scorecard_date}
                    </p>
                    {checks.map((c, i) => (
                      <div key={i} className="flex items-start justify-between gap-3 border-b border-border/60 py-1.5 text-xs">
                        <div>
                          <div className="font-medium">{c.name}</div>
                          <div className="text-xs text-muted-foreground">{c.reason}</div>
                        </div>
                        <span className="font-mono text-warning">{c.score ?? "—"}</span>
                      </div>
                    ))}
                  </>
                )}
              </div>
            )}

            <div className="mt-3 flex justify-end gap-2">
              <Button size="sm" variant="outline" disabled={rescanning} onClick={() => void rescan(false)}>
                <LinkIcon aria-hidden /> Re-resolve
              </Button>
              <Button size="sm" variant="outline" disabled={rescanning} onClick={() => void rescan(true)}>
                <LinkIcon aria-hidden /> Re-resolve + scan transitive
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
