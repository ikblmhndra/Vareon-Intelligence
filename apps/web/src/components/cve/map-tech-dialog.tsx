"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { XIcon } from "lucide-react";

import { api } from "@/lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  targetLabel,
  useDebounced,
  useMonitorActions,
  type CatalogRef,
  type TechStackOut,
} from "@/lib/cve/catalog";

const MIN_QUERY = 2;
const RESULTS = 10;

interface MapTechDialogProps {
  /** Entri yang diatur (diambil dari daftar terkini oleh pemanggil, jadi ikut segar setelah aksi). */
  entry: TechStackOut | null;
  onOpenChange: (open: boolean) => void;
}

/**
 * Editor target satu entri Monitor. Untuk entri lama tanpa target ("Map to catalog"): cari di
 * katalog (terisi nama entri), pilih produk atau vendor sebagai target PERTAMA, dan entri berhenti
 * dicocokkan lewat teks nama dan dicocokkan lewat katalog. Untuk entri katalog ("Targets"): tambah
 * target (mis. `junos` -> tiga produk Juniper) atau lepas target. Dialog tetap terbuka supaya
 * beberapa target bisa ditambahkan berurutan.
 *
 * Target terakhir tidak bisa dilepas (backend menolak, 409): entri tanpa target kembali dicocokkan
 * lewat teks. Hapus atau nonaktifkan entri bila memang tidak ingin dipantau.
 */
export function MapTechDialog({ entry, onOpenChange }: MapTechDialogProps) {
  return (
    <Dialog open={entry !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        {entry && <MapTechBody key={entry.id} entry={entry} onClose={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}

function MapTechBody({ entry, onClose }: { entry: TechStackOut; onClose: () => void }) {
  const actions = useMonitorActions();
  const [search, setSearch] = useState(entry.name);
  const q = useDebounced(search.trim()).toLowerCase();
  const searching = q.length >= MIN_QUERY;
  const unmapped = entry.targets.length === 0;

  const have = new Set(entry.targets.map((t) => (t.kind === "vendor" ? `v${t.vendor_id}` : `f${t.family_id}`)));

  const products = useQuery({
    queryKey: ["catalog", "families", "map", q],
    enabled: searching,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/catalog/families", {
        params: { query: { q, page: 1, page_size: RESULTS } },
      });
      if (error) throw error;
      return data;
    },
  });
  const vendors = useQuery({
    queryKey: ["catalog", "vendors", "map", q],
    enabled: searching,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/catalog/vendors", {
        params: { query: { q, show_all: true, page: 1, page_size: RESULTS } },
      });
      if (error) throw error;
      return data;
    },
  });

  function add(ref: CatalogRef) {
    void actions.addTarget(entry.id, ref);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle className="font-heading">
          {unmapped ? "Map to catalog" : "Targets"}: <span className="font-mono">{entry.name}</span>
        </DialogTitle>
        <DialogDescription>
          {unmapped
            ? "This entry is matched by its name as plain text. Pick the catalog product (or vendor) it stands for, and CVEs will be matched by identity instead."
            : "CVEs affecting any of these targets are matched to this entry. Add more (e.g. several products of one vendor)."}
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="text-muted-foreground">Current:</span>
        {unmapped && <Badge variant="outline">none — matched by name text</Badge>}
        {entry.targets.map((t) => (
          <Badge key={t.id} variant="secondary" className="gap-1 pr-1">
            {targetLabel(t)}
            <button
              type="button"
              aria-label={`Remove target ${targetLabel(t)}`}
              disabled={actions.busy || entry.targets.length <= 1}
              title={entry.targets.length <= 1 ? "The last target cannot be removed" : "Remove target"}
              className="rounded-full p-0.5 hover:bg-background/60 disabled:opacity-40"
              onClick={() => void actions.removeTarget(entry.id, t.id)}
            >
              <XIcon className="size-3" />
            </button>
          </Badge>
        ))}
      </div>

      <Input
        autoFocus
        placeholder="Search the catalog (vendor or product)…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="font-mono text-xs"
      />

      <div className="max-h-80 overflow-y-auto">
        {!searching && <p className="py-4 text-center text-xs text-muted-foreground">Type at least {MIN_QUERY} characters.</p>}
        {searching && (products.isPending || vendors.isPending) && (
          <p className="py-4 text-center text-xs text-muted-foreground">Searching…</p>
        )}
        {searching && products.data && vendors.data && products.data.total === 0 && vendors.data.total === 0 && (
          <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            No catalog match for “{q}”. The catalog uses the names that vendors publish in CVEs, which can differ from this
            label (for example FortiGate is published as <strong>FortiOS</strong>). Try the vendor name or the product&apos;s
            formal name.
          </p>
        )}
        {searching && products.data && vendors.data && (
          <div className="flex flex-col gap-4">
            <section>
              <h4 className="mb-1 text-xs font-medium text-muted-foreground">
                Products ({products.data.total}) — most precise
              </h4>
              {products.data.items.length === 0 && <p className="text-xs text-muted-foreground">No product matches.</p>}
              {products.data.items.map((f) => (
                <ResultRow
                  key={f.id}
                  title={f.display_name}
                  subtitle={`${f.vendor_name} · ${f.cve_seen_total.toLocaleString()} CVE`}
                  added={have.has(`f${f.id}`)}
                  busy={actions.busy}
                  onAdd={() => add({ family_id: f.id })}
                />
              ))}
            </section>
            <section>
              <h4 className="mb-1 text-xs font-medium text-muted-foreground">
                Vendors ({vendors.data.total}) — every product of the vendor
              </h4>
              {vendors.data.items.length === 0 && <p className="text-xs text-muted-foreground">No vendor matches.</p>}
              {vendors.data.items.map((v) => (
                <ResultRow
                  key={v.id}
                  title={v.display_name}
                  subtitle={`${v.family_count} products · ${v.cve_seen_total.toLocaleString()} CVE`}
                  added={have.has(`v${v.id}`)}
                  disabledReason={v.monitorable ? undefined : "no vendor identity"}
                  busy={actions.busy}
                  onAdd={() => add({ vendor_id: v.id })}
                />
              ))}
            </section>
          </div>
        )}
      </div>

      <div className="flex justify-end">
        <Button variant="outline" onClick={onClose}>
          Done
        </Button>
      </div>
    </>
  );
}

function ResultRow({
  title,
  subtitle,
  added,
  disabledReason,
  busy,
  onAdd,
}: {
  title: string;
  subtitle: string;
  added: boolean;
  disabledReason?: string;
  busy: boolean;
  onAdd: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border/60 py-1.5 last:border-0">
      <div className="min-w-0">
        <div className="truncate text-sm">{title}</div>
        <div className="truncate text-xs text-muted-foreground">{subtitle}</div>
      </div>
      <Button size="sm" variant="outline" disabled={busy || added || !!disabledReason} title={disabledReason} onClick={onAdd}>
        {added ? "Added" : "Add"}
      </Button>
    </div>
  );
}
