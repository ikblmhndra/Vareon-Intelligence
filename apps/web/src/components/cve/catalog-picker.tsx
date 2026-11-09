"use client";

import { useQuery } from "@tanstack/react-query";

import { Chip } from "@/components/ui/chip";
import { RadioList } from "@/components/ui/radio-list";
import { api } from "@/lib/api/client";
import type { CatalogRef } from "@/lib/cve/catalog";
import { fmtCompactAge } from "@/lib/format";

const MIN_QUERY = 2;
const RESULTS = 10;

/** Kunci stabil satu rujukan katalog ("f12" produk, "v3" vendor): value RadioList dan himpunan `taken`. */
export function refKey(r: CatalogRef): string {
  return "vendor_id" in r ? `v${r.vendor_id}` : `f${r.family_id}`;
}

interface CatalogPickerProps {
  /** Kata kunci (sudah di-debounce oleh pemanggil). Di bawah 2 huruf = petunjuk, tanpa request. */
  q: string;
  value: CatalogRef | null;
  /** `label` = nama tampilan baris terpilih (untuk tombol "Map to {name}"). */
  onChange: (r: CatalogRef, label: string) => void;
  /** Baris MONITORED / COVERED BY VENDOR tidak bisa dipilih (Add from catalog). */
  disableMonitored?: boolean;
  /** Rujukan yang sudah jadi target entri (Map to catalog): tidak bisa dipilih lagi. */
  taken?: ReadonlySet<string>;
}

/** Picker katalog bersama Map dan Add from catalog: produk (paling presisi) dan vendor utuh dalam satu
 * `RadioList`. Produk "{vendor} - {product}", vendor "{vendor} (whole vendor)". */
export function CatalogPicker({ q, value, onChange, disableMonitored, taken }: CatalogPickerProps) {
  const searching = q.length >= MIN_QUERY;

  const products = useQuery({
    queryKey: ["catalog", "families", "picker", q],
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
    queryKey: ["catalog", "vendors", "picker", q],
    enabled: searching,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/catalog/vendors", {
        params: { query: { q, show_all: true, page: 1, page_size: RESULTS } },
      });
      if (error) throw error;
      return data;
    },
  });

  if (!searching) {
    return <p className="py-6 text-center text-xs text-muted-foreground">Type at least {MIN_QUERY} characters to search the catalog.</p>;
  }
  if (products.isPending || vendors.isPending) {
    return (
      <p role="status" className="py-6 text-center text-xs text-muted-foreground">
        Searching…
      </p>
    );
  }
  if (products.isError || vendors.isError) {
    return (
      <p role="alert" className="py-6 text-center text-xs text-destructive-text">
        Catalog search failed. Try again.
      </p>
    );
  }

  const blocked = (key: string, monitored: boolean) => (disableMonitored && monitored) || (taken?.has(key) ?? false);

  const options = [
    ...products.data.items.map((f) => {
      const key = refKey({ family_id: f.id });
      return {
        value: key,
        title: `${f.vendor_name} - ${f.display_name}`,
        sub: (
          <span className="inline-flex flex-wrap items-center gap-1.5">
            {f.vendor_name} - last CVE {fmtCompactAge(f.last_cve_at)}
            {f.source === "custom" && <Chip kind="flag" value="custom" />}
          </span>
        ),
        aside: f.monitored ? (
          <Chip kind="cve" value="monitored" />
        ) : f.covered_by_vendor ? (
          <Chip kind="cve" value="covered_by_vendor" />
        ) : (
          `${f.cve_seen_total.toLocaleString()} CVEs`
        ),
        disabled: blocked(key, f.monitored || f.covered_by_vendor),
      };
    }),
    ...vendors.data.items.map((v) => {
      const key = refKey({ vendor_id: v.id });
      return {
        value: key,
        title: `${v.display_name} (whole vendor)`,
        sub: `Watches every ${v.display_name} product - ${v.family_count} products`,
        aside: v.monitored ? <Chip kind="cve" value="monitored" /> : `${v.cve_seen_total.toLocaleString()} CVEs`,
        disabled: !v.monitorable || blocked(key, v.monitored),
      };
    }),
  ];

  if (options.length === 0) {
    return (
      <p className="rounded-lg bg-surface px-3 py-3 text-xs text-muted-foreground">
        No catalog match for “{q}”. The catalog uses the names vendors publish in CVEs, which can differ from your label
        (FortiGate is published as FortiOS). Try the vendor name or the product&apos;s formal name.
      </p>
    );
  }

  const productKeys = new Map<string, CatalogRef>();
  for (const f of products.data.items) productKeys.set(refKey({ family_id: f.id }), { family_id: f.id });
  for (const v of vendors.data.items) productKeys.set(refKey({ vendor_id: v.id }), { vendor_id: v.id });
  const labels = new Map(options.map((o) => [o.value, o.title]));

  return (
    <div className="max-h-72 overflow-y-auto pr-1">
      <RadioList
        name="catalog-target"
        aria-label="Catalog results"
        value={value ? refKey(value) : null}
        options={options}
        onChange={(k) => {
          const ref = productKeys.get(k);
          if (ref) onChange(ref, labels.get(k) ?? "");
        }}
      />
    </div>
  );
}
