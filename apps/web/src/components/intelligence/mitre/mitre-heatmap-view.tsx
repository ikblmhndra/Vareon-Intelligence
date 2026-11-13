"use client";

import Link from "next/link";
import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { AttackDataCard } from "@/components/intelligence/mitre/attack-data-card";
import { TtpDrillCard, type TtpDrillTarget } from "@/components/intelligence/mitre/ttp-drill-card";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FilterSelect } from "@/components/ui/filter-select";
import { HeatCell, HeatGrid } from "@/components/ui/heat-grid";
import { LegendRow } from "@/components/ui/legend-row";
import { PresetControl } from "@/components/ui/preset-control";
import { RowMenu } from "@/components/ui/row-menu";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { StatePanel } from "@/components/ui/state-panel";
import { api, proxyFetch } from "@/lib/api/client";
import { getActiveClientId } from "@/lib/auth/client-id";
import type { MitreHeatmapResponse } from "@/lib/api/loose-types";

type View = "ta" | "industry";

const VIEWS = [
  { value: "ta", label: "Actors" },
  { value: "industry", label: "Industries" },
] as const;
const PERIODS = [
  { value: 30, label: "30d" },
  { value: 90, label: "90d" },
  { value: 180, label: "180d" },
  { value: 365, label: "365d" },
] as const;
// Batas API: top_rows 3-30, top_ttps 5-40.
const ROW_COUNTS = [5, 10, 15, 20, 30];
const COL_COUNTS = [8, 12, 20, 30, 40];

/** Lima langkah warna dari `count / max_val`; sel berisi minimal langkah 1 supaya tak tampak kosong. */
function stepOf(val: number, max: number): 1 | 2 | 3 | 4 | 5 {
  return Math.min(5, Math.max(1, Math.ceil((val * 5) / max))) as 1 | 2 | 3 | 4 | 5;
}

const LEGEND_SWATCHES = ["bg-primary/20", "bg-primary/30", "bg-primary/40", "bg-primary/45", "bg-primary"] as const;

/** Legenda 0 -> max: sel kosong + lima langkah dengan rentang jumlah artikelnya (hasil `stepOf`, aritmetika
 * bilangan bulat). Langkah yang tak mungkin tercapai (max kecil, mis. 3) dibuang supaya legenda jujur. */
function legendItems(max: number) {
  const items = [{ label: "0", swatchClass: "border border-border bg-background" }];
  LEGEND_SWATCHES.forEach((swatchClass, i) => {
    const lo = Math.floor((max * i) / 5) + 1;
    const hi = Math.floor((max * (i + 1)) / 5);
    if (lo > hi) return;
    items.push({ label: lo === hi ? String(lo) : `${lo}-${hi}`, swatchClass });
  });
  return items;
}

/** Heatmap TTP OBSERVED di artikel (`ArticleTTP`; beda dari katalog teknik di Entities). Port
 * `loadMitreHeatmap()`/`downloadNavigatorLayer()`/`openNavigator()` (`scraper.js:68-182`). Memilih sel membuka
 * kartu drill di bawah (dulu dialog). Layer Navigator memakai view/days/baris/kolom yang dipilih, jadi sama
 * dengan heatmap yang terlihat. */
export function MitreHeatmapView() {
  const [view, setView] = useState<View>("ta");
  const [days, setDays] = useState(90);
  const [topRows, setTopRows] = useState(10);
  const [topTtps, setTopTtps] = useState(12);
  // Kunci "baris||ttp"; bila sel hilang (filter berubah) jatuh ke sel terpanas.
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const query = useQuery({
    queryKey: ["intelligence", "mitre-heatmap", view, days, topRows, topTtps],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/mitre/heatmap", {
        params: { query: { view, days, top_rows: topRows, top_ttps: topTtps } },
      });
      if (error) throw error;
      return data as unknown as MitreHeatmapResponse;
    },
    // Ganti filter tanpa mengosongkan grid: data lama tampil sampai yang baru tiba.
    placeholderData: keepPreviousData,
  });

  async function downloadLayer() {
    setExporting(true);
    try {
      const clientId = getActiveClientId();
      const resp = await proxyFetch(
        `/api/proxy/api/mitre/navigator-export?view=${view}&days=${days}&top_rows=${topRows}&top_ttps=${topTtps}`,
        clientId ? { headers: { "X-Client-ID": clientId } } : undefined,
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `cti_navigator_${view}_${days}d_r${topRows}_c${topTtps}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } finally {
      setExporting(false);
    }
  }

  /** `#layerURL=` tidak bisa dipakai: Navigator (mitre-attack.github.io) mengambil layer dari
   * browser TANPA cookie sesi (proxy menolak), dan app di http internal diblokir sebagai mixed
   * content. Jadi: buka Navigator (sinkron di handler klik supaya tidak kena popup blocker),
   * unduh layer yang sama dengan tombol Export, lalu tunjukkan cara memuatnya. */
  async function openNavigator() {
    window.open("https://mitre-attack.github.io/attack-navigator/", "_blank", "noopener");
    try {
      await downloadLayer();
      // Tetap tampil sampai ditutup: user biasanya sedang di tab Navigator saat toast muncul.
      toast.info("Layer downloaded", {
        description:
          "In ATT&CK Navigator choose Open Existing Layer → Upload from local, then pick the downloaded JSON. If no tab opened, go to mitre-attack.github.io/attack-navigator.",
        duration: Infinity,
        closeButton: true,
      });
    } catch {
      toast.error("Failed to download the layer.");
    }
  }

  const d = query.data;
  const max = d?.max_val || 1;
  const hasData = !!d && d.rows.length > 0 && d.ttps.length > 0;

  // Sel terpanas (pertama bila seri) = pilihan awal.
  let maxCell: [number, number] | null = null;
  if (d && hasData) {
    let best = 0;
    d.matrix.forEach((r, ri) =>
      r.forEach((v, ci) => {
        if (v > best) {
          best = v;
          maxCell = [ri, ci];
        }
      }),
    );
  }
  let active: [number, number] | null = maxCell;
  if (d && hasData && selectedKey) {
    const [rowName, ttpId] = selectedKey.split("||");
    const ri = d.rows.indexOf(rowName);
    const ci = d.ttps.findIndex((t) => t.id === ttpId);
    if (ri >= 0 && ci >= 0) active = [ri, ci];
  }

  const rowNoun = view === "ta" ? "actors" : "industries";
  const target: TtpDrillTarget | null =
    d && hasData && active
      ? {
          ttpId: d.ttps[active[1]].id,
          ttpName: d.ttps[active[1]].name,
          ttpEntityId: d.ttps[active[1]].entity_id,
          row: d.rows[active[0]],
          rowEntityId: d.row_ids?.[active[0]],
          view,
          days,
        }
      : null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          <div className="flex flex-col gap-1">
            <span className="text-2xs font-semibold tracking-wide text-muted-foreground uppercase">View</span>
            <SegmentedControl
              aria-label="Heatmap view"
              options={VIEWS}
              value={view}
              onChange={(v) => {
                setView(v);
                setSelectedKey(null);
              }}
            />
          </div>
          <PresetControl
            label="Period"
            aria-label="Period days"
            presets={PERIODS}
            value={days}
            onChange={setDays}
            min={7}
            max={365}
            step={1}
          />
          <div className="flex flex-col gap-1">
            <span className="text-2xs font-semibold tracking-wide text-muted-foreground uppercase">Size</span>
            <div className="flex flex-wrap gap-2">
              <FilterSelect
                prefix="Rows"
                aria-label="Number of rows"
                value={String(topRows)}
                onChange={(v) => setTopRows(Number(v))}
                options={ROW_COUNTS.map((n) => ({ value: String(n), label: `Top ${n} ${rowNoun}` }))}
              />
              <FilterSelect
                prefix="Columns"
                aria-label="Number of techniques"
                value={String(topTtps)}
                onChange={(v) => setTopTtps(Number(v))}
                options={COL_COUNTS.map((n) => ({ value: String(n), label: `Top ${n} techniques` }))}
              />
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant="outline"
            disabled={exporting}
            onClick={() => void downloadLayer().catch(() => toast.error("Failed to download the layer."))}
          >
            Export ATT&amp;CK Navigator layer
          </Button>
          <RowMenu
            label="More export actions"
            items={[{ label: "Open in ATT&CK Navigator", onSelect: () => void openNavigator() }]}
          />
        </div>
      </div>

      {query.isPending && (
        <StatePanel variant="loading" title="Loading heatmap" description="Counting articles per technique." />
      )}
      {query.isError && (
        <StatePanel
          variant="error"
          title="Failed to load the heatmap"
          action={
            <Button variant="outline" size="sm" onClick={() => query.refetch()}>
              Retry
            </Button>
          }
        />
      )}
      {d && !hasData && (
        <StatePanel
          variant="empty"
          title="No TTP data for this period"
          description="Try a longer period."
        />
      )}

      {d && hasData && (
        <Card>
          <div className="flex flex-col gap-3 px-5">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h2 className="font-heading text-base font-semibold">
                  {view === "ta" ? "Actor" : "Industry"} × technique
                </h2>
                <p className="text-xs text-muted-foreground">
                  Articles mentioning both · max {d.max_val}
                </p>
              </div>
              <LegendRow items={legendItems(d.max_val)} />
            </div>
            <HeatGrid
              aria-label={`Articles by ${view === "ta" ? "actor" : "industry"} and technique`}
              rowLabels={d.rows.map((r) => (
                <span key={r} className="block max-w-44 truncate" title={r}>
                  {r}
                </span>
              ))}
              colLabels={d.ttps.map((t) => (
                <div key={t.id} className="w-20 max-w-24 py-0.5">
                  {t.entity_id != null ? (
                    <Link
                      href={`/intelligence/entities/${t.entity_id}`}
                      className="rounded-sm font-code text-primary-text underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                    >
                      {t.id}
                    </Link>
                  ) : (
                    <span className="font-code text-primary-text">{t.id}</span>
                  )}
                  <span className="block font-normal break-words" title={t.name}>
                    {t.name}
                  </span>
                </div>
              ))}
              active={active}
              onSelect={(r, c) => setSelectedKey(`${d.rows[r]}||${d.ttps[c].id}`)}
              renderCell={(r, c) => {
                const val = d.matrix[r]?.[c] ?? 0;
                const label = `${d.rows[r]} × ${d.ttps[c].id}`;
                const selected = active?.[0] === r && active?.[1] === c;
                if (val <= 0) {
                  return (
                    <HeatCell
                      variant="scale"
                      value={null}
                      selected={selected}
                      aria-label={`${label}, no articles`}
                    />
                  );
                }
                return (
                  <HeatCell
                    variant="scale"
                    value={val}
                    step={stepOf(val, max)}
                    selected={selected}
                    aria-label={`${label}, ${val} articles`}
                    title={`${label}: ${val} articles`}
                  />
                );
              }}
            />
          </div>
        </Card>
      )}

      {target && (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          <TtpDrillCard
            key={`${target.view}|${target.days}|${target.row}|${target.ttpId}`}
            target={target}
          />
          <AttackDataCard />
        </div>
      )}
      {!target && (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          <div className="hidden lg:block" />
          <AttackDataCard />
        </div>
      )}
    </div>
  );
}
