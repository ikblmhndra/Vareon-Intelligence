"use client";

import { useState } from "react";
import { Copy, Download } from "lucide-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { HuntHypothesis } from "@/components/hunt/hunt-hypothesis";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { getActiveClientId } from "@/lib/auth/client-id";

type AnchorType = "story" | "entity";
type Include = "inferred" | "llm";
type HuntIoc = components["schemas"]["HuntIocOut"];
type HuntPack = components["schemas"]["HuntPackOut"];

const TIERS = [
  { tier: "primary", label: "Primary" },
  { tier: "inferred", label: "Inferred (ATT&CK)" },
  { tier: "llm", label: "LLM suggested" },
] as const;

const INCLUDE_ITEMS: { value: Include; label: string }[] = [
  { value: "inferred", label: "Include inferred techniques" },
  { value: "llm", label: "Include LLM-suggested techniques" },
];

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function iocsCsv(rows: HuntIoc[]): string {
  const cell = (v: string) => `"${v.replace(/"/g, '""')}"`;
  return ["type,value,valid_until,tlp", ...rows.map((r) => [r.type, r.value, r.valid_until ?? "", r.tlp].map(cell).join(","))].join("\r\n");
}

/**
 * Hunting pack (P7e 7.1) untuk story atau entity: teknik per tier, SPL per dataset, aturan Sigma,
 * unduhan zip/CSV, dan draf hipotesis. Di newsroom (`story`) panel disembunyikan bila pack tidak punya
 * teknik maupun indikator, juga saat memuat/gagal (mis. user tanpa `view_ioc`) supaya modal tetap bersih.
 */
export function HuntPanel({ anchorType, anchorId }: { anchorType: AnchorType; anchorId: number }) {
  const [include, setInclude] = useState<Include[]>([]);
  const [downloading, setDownloading] = useState(false);
  const isStory = anchorType === "story";

  const pack = useQuery({
    queryKey: ["hunt-pack", anchorType, anchorId, include],
    // Data lama tetap tampil saat checkbox include memicu refetch (tanpa kedip/hilang).
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/hunt-packs/{anchor_type}/{anchor_id}", {
        params: { path: { anchor_type: anchorType, anchor_id: anchorId }, query: { include } },
      });
      if (!data) throw new Error(`HTTP ${response.status}`);
      // Skema 200 juga memuat cabang `application/zip` (string); tanpa `format=zip` selalu JSON.
      return data as HuntPack;
    },
  });

  async function downloadZip() {
    setDownloading(true);
    try {
      const qs = new URLSearchParams([["format", "zip"], ...include.map((i) => ["include", i])]);
      const clientId = getActiveClientId();
      const resp = await fetch(
        `/api/proxy/api/hunt-packs/${anchorType}/${anchorId}?${qs}`,
        clientId ? { headers: { "X-Client-ID": clientId } } : undefined,
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      saveBlob(await resp.blob(), `hunt-${anchorType}-${anchorId}.zip`);
    } catch (e) {
      toast.error(`Download failed: ${(e as Error).message}`);
    } finally {
      setDownloading(false);
    }
  }

  async function copy(text: string) {
    try {
      // `navigator.clipboard` tidak ada di origin non-secure (dev http://172.25.1.77): pakai textarea + execCommand.
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const prev = document.activeElement as HTMLElement | null;
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        // Di pojok viewport + preventScroll supaya select() tidak menggulir halaman.
        Object.assign(ta.style, { position: "fixed", top: "0", left: "0", opacity: "0", pointerEvents: "none" });
        document.body.appendChild(ta);
        let ok = false;
        try {
          ta.focus({ preventScroll: true });
          ta.select();
          ok = document.execCommand("copy");
        } finally {
          ta.remove();
          prev?.focus({ preventScroll: true });
        }
        if (!ok) throw new Error("execCommand failed");
      }
      toast.success("Copied to clipboard");
    } catch {
      toast.error("Could not copy to clipboard. Select the query text and copy it manually.");
    }
  }

  if (pack.isPending) return isStory ? null : <Skeleton className="h-48 w-full" />;
  if (pack.isError) {
    return isStory ? null : (
      <p role="alert" className="text-sm text-destructive">
        Could not load the hunting pack. Try again later.
      </p>
    );
  }
  const p = pack.data;
  const datasets = Object.entries(p.iocs).filter(([, rows]) => rows.length > 0);
  if (isStory && p.techniques.length === 0 && datasets.length === 0) return null;
  const skipped = p.counts.skipped_values ?? 0;
  const headingId = `hunt-${anchorType}-${anchorId}`;

  return (
    <section
      aria-labelledby={headingId}
      className={isStory ? "min-w-0 space-y-4" : "surface-raised min-w-0 space-y-4 rounded-xl p-5"}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2
          id={headingId}
          className={isStory ? "text-sm font-semibold text-muted-foreground" : "text-base font-semibold"}
        >
          Hunt
        </h2>
        <Button variant="outline" size="sm" className="max-sm:h-11" disabled={downloading} onClick={downloadZip}>
          <Download aria-hidden />
          {downloading ? "Preparing…" : "Download pack (zip)"}
        </Button>
      </div>

      <div className="flex flex-wrap gap-x-5 gap-y-2" aria-busy={pack.isFetching}>
        {INCLUDE_ITEMS.map((it) => (
          <div key={it.value} className="flex items-center gap-2">
            <Checkbox
              id={`${headingId}-${it.value}`}
              aria-label={it.label}
              checked={include.includes(it.value)}
              onCheckedChange={(on) =>
                setInclude((cur) => (on ? [...cur, it.value] : cur.filter((x) => x !== it.value)))
              }
            />
            <Label htmlFor={`${headingId}-${it.value}`} className="text-xs font-normal">
              {it.label}
            </Label>
          </div>
        ))}
      </div>

      {p.truncated && (
        <p className="text-xs text-warning-text">
          Indicators were capped at the newest {(p.counts.indicators ?? 0).toLocaleString()}; older ones are not in this pack.
        </p>
      )}
      {skipped > 0 && (
        <p className="text-xs text-muted-foreground">
          {skipped.toLocaleString()} values containing <span className="font-code">*</span> (or a control character) were
          left out of the SPL searches, because <span className="font-code">*</span> is a wildcard in SPL.
        </p>
      )}

      <div className="space-y-2">
        <h3 className="text-sm font-semibold">
          Techniques <span className="text-xs font-normal text-muted-foreground">{p.techniques.length} total</span>
        </h3>
        {p.techniques.length === 0 ? (
          <p className="text-xs text-muted-foreground">No techniques for this pack.</p>
        ) : (
          TIERS.map(({ tier, label }) => {
            const items = p.techniques.filter((t) => t.tier === tier);
            if (items.length === 0) return null;
            return (
              <div key={tier} className="space-y-1">
                <div className="text-2xs font-semibold tracking-wide text-muted-foreground uppercase">{label}</div>
                <div className="flex flex-wrap gap-1.5">
                  {items.map((t) => (
                    <Badge key={t.attack_id} variant="outline" className="h-auto whitespace-normal">
                      <span className="font-code">{t.attack_id}</span> {t.name}
                      {t.sigma_count > 0 && <span className="text-muted-foreground">· {t.sigma_count} Sigma</span>}
                    </Badge>
                  ))}
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-semibold">Splunk searches</h3>
        {p.spl.length === 0 ? (
          <p className="text-xs text-muted-foreground">No indicators to search for.</p>
        ) : (
          p.spl.map((s) => (
            <div key={`${s.dataset}-${s.chunk}`} className="min-w-0 rounded-md border border-border bg-muted/30">
              <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-1.5">
                <span className="min-w-0 text-xs break-words">
                  <span className="font-code">{s.dataset}</span> · {s.value_count.toLocaleString()} values
                </span>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="max-sm:size-11"
                  aria-label={`Copy SPL for ${s.dataset}`}
                  onClick={() => void copy(s.query)}
                >
                  <Copy aria-hidden />
                </Button>
              </div>
              <pre className="max-h-64 overflow-auto p-3 font-code text-xs">{s.query}</pre>
            </div>
          ))
        )}
        {datasets.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">Indicators as CSV:</span>
            {datasets.map(([dataset, rows]) => (
              <Button
                key={dataset}
                variant="outline"
                size="sm"
                className="max-sm:h-11"
                onClick={() =>
                  saveBlob(new Blob([iocsCsv(rows)], { type: "text/csv" }), `hunt-${anchorType}-${anchorId}-${dataset}.csv`)
                }
              >
                <Download aria-hidden />
                <span className="font-code">{dataset}</span>
              </Button>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-semibold">
          Sigma rules <span className="text-xs font-normal text-muted-foreground">{p.sigma.length} total</span>
        </h3>
        {p.sigma.length === 0 ? (
          <p className="text-xs text-muted-foreground">No Sigma rules match these techniques.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Level</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Author</TableHead>
                <TableHead>Logsource</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {p.sigma.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="min-w-48 text-xs whitespace-normal">
                    <a
                      href={r.link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded-sm text-primary-text underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-focus"
                    >
                      {r.title}
                    </a>
                    <div className="text-2xs text-muted-foreground">
                      via <span className="font-code">{r.via_technique}</span> ({r.match})
                    </div>
                  </TableCell>
                  <TableCell className="text-xs">{r.level}</TableCell>
                  <TableCell className="text-xs">{r.status}</TableCell>
                  <TableCell className="min-w-32 text-xs whitespace-normal">{r.author || "-"}</TableCell>
                  <TableCell className="font-code text-xs">
                    {Object.values(r.logsource).join(" / ") || "-"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <p className="text-2xs text-muted-foreground">
          Sigma rules by their authors, licensed under the{" "}
          <a
            href="https://github.com/SigmaHQ/Detection-Rule-License"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary-text underline underline-offset-2"
          >
            Detection Rule License 1.1
          </a>
          . Source:{" "}
          <a
            href="https://github.com/SigmaHQ/sigma"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary-text underline underline-offset-2"
          >
            SigmaHQ
          </a>
          {p.sigma_release && <> (release {p.sigma_release})</>}.
        </p>
      </div>

      <HuntHypothesis anchorType={anchorType} anchorId={anchorId} />
    </section>
  );
}
