"use client";

import { DownloadIcon } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { getActiveClientId } from "@/lib/auth/client-id";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { MitreHeatmapResponse } from "@/lib/api/loose-types";
import { TtpDrillDialog, type TtpDrillTarget } from "@/components/intelligence/mitre/ttp-drill-dialog";

const VIEWS = [
  { value: "ta", label: "Threat Actor" },
  { value: "industry", label: "Industry" },
] as const;
const DAY_OPTIONS = [30, 90, 180, 365];

/** Port `loadMitreHeatmap()`/`downloadNavigatorLayer()`/`openNavigator()`
 * (`scraper.js:68-182`) -- heatmap TTP OBSERVED di artikel (`ArticleTTP`,
 * beda dari katalog ATT&CK DB di bawah). Klik sel -> `TtpDrillDialog`. */
export function MitreHeatmapView() {
  const [view, setView] = useState<"ta" | "industry">("ta");
  const [days, setDays] = useState(90);
  const [drillTarget, setDrillTarget] = useState<TtpDrillTarget | null>(null);
  const [exporting, setExporting] = useState(false);

  const query = useQuery({
    queryKey: ["intelligence", "mitre-heatmap", view, days],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/mitre/heatmap", { params: { query: { view, days } } });
      if (error) throw error;
      return data as unknown as MitreHeatmapResponse;
    },
  });

  async function downloadLayer() {
    setExporting(true);
    try {
      const clientId = getActiveClientId();
      const resp = await fetch(
        `/api/proxy/api/mitre/navigator-export?view=${view}&days=${days}`,
        clientId ? { headers: { "X-Client-ID": clientId } } : undefined,
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `cti_navigator_${view}_${days}d.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } finally {
      setExporting(false);
    }
  }

  function openNavigator() {
    const layerUrl = encodeURIComponent(`${window.location.origin}/api/proxy/api/mitre/navigator-layer?view=${view}&days=${days}`);
    window.open(`https://mitre-attack.github.io/attack-navigator/#layerURL=${layerUrl}`, "_blank");
  }

  const d = query.data;
  const max = d?.max_val || 1;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">View</Label>
          <Select value={view} onValueChange={(v) => v && setView(v as "ta" | "industry")}>
            <SelectTrigger size="sm" className="w-36 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {VIEWS.map((v) => (
                <SelectItem key={v.value} value={v.value} className="font-mono text-xs">
                  {v.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Period</Label>
          <Select value={String(days)} onValueChange={(v) => v && setDays(Number(v))}>
            <SelectTrigger size="sm" className="w-28 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DAY_OPTIONS.map((dOpt) => (
                <SelectItem key={dOpt} value={String(dOpt)} className="font-mono text-xs">
                  {dOpt} days
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="outline" disabled={exporting} onClick={() => void downloadLayer()}>
            <DownloadIcon /> Download Layer
          </Button>
          <Button size="sm" variant="outline" onClick={openNavigator}>
            ⧉ Open in Navigator
          </Button>
        </div>
      </div>

      {query.isPending && <p className="py-8 text-center text-xs text-muted-foreground">Loading…</p>}
      {query.isError && <p className="py-8 text-center text-xs text-destructive">Failed to load heatmap.</p>}
      {d && (d.rows.length === 0 || d.ttps.length === 0) && (
        <p className="py-8 text-center text-xs text-muted-foreground">No TTP data for this period.</p>
      )}

      {d && d.rows.length > 0 && d.ttps.length > 0 && (
        <div className="overflow-x-auto rounded-2xl surface-raised p-4">
          <table className="border-collapse text-xs">
            <thead>
              <tr>
                <th className="border border-border bg-surface px-2 py-1.5 text-left text-muted-foreground">
                  {view === "ta" ? "Threat Actor" : "Industry"}
                </th>
                {d.ttps.map((t) => (
                  <th
                    key={t.id}
                    className="border border-border bg-surface px-1.5 py-1.5 font-mono text-muted-foreground"
                    title={`${t.id} — ${t.name}`}
                  >
                    {t.id}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.rows.map((row, ri) => (
                <tr key={row}>
                  <td className="max-w-[160px] truncate border border-border bg-surface px-2 py-1 whitespace-nowrap text-foreground" title={row}>
                    {row}
                  </td>
                  {d.matrix[ri].map((val, ci) => {
                    const t = d.ttps[ci];
                    const intensity = val && max ? val / max : 0;
                    return (
                      <td
                        key={t.id}
                        className="min-w-[36px] border border-border px-1 py-1 text-center font-mono"
                        style={{
                          background: intensity > 0 ? `color-mix(in srgb, var(--primary) ${Math.round(intensity * 85 + 8)}%, transparent)` : undefined,
                          color: intensity > 0.75 ? "var(--primary-foreground)" : intensity > 0 ? "var(--foreground)" : undefined,
                          cursor: val > 0 ? "pointer" : undefined,
                        }}
                        title={`${row} × ${t.id}: ${val} articles`}
                        onClick={() => val > 0 && setDrillTarget({ ttpId: t.id, ttpName: t.name, row, view, days })}
                      >
                        {val || ""}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <TtpDrillDialog target={drillTarget} onClose={() => setDrillTarget(null)} />
    </div>
  );
}
