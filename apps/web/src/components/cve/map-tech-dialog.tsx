"use client";

import { useState } from "react";
import { XIcon } from "lucide-react";

import { CatalogPicker, refKey } from "@/components/cve/catalog-picker";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { SearchInput } from "@/components/ui/search-input";
import { targetLabel, useDebounced, useMonitorActions, type CatalogRef, type TechStackOut } from "@/lib/cve/catalog";

interface MapTechDialogProps {
  /** Entri yang diatur (diambil dari daftar terkini oleh pemanggil, jadi ikut segar setelah aksi). */
  entry: TechStackOut | null;
  onOpenChange: (open: boolean) => void;
}

/**
 * Editor target satu entri Monitor. Entri lama tanpa target ("Map to catalog"): cari di katalog
 * (terisi nama entri), pilih produk atau vendor, dan entri berhenti dicocokkan lewat teks nama.
 * Entri yang sudah punya target ("Targets", D14): daftar target saat ini di atas picker, tiap
 * target bisa dilepas dan target baru ditambahkan (mis. `junos` -> tiga produk Juniper); dialog
 * tetap terbuka supaya beberapa target bisa ditambah berurutan.
 *
 * Target terakhir tidak bisa dilepas (backend menolak, 409): entri tanpa target kembali dicocokkan
 * lewat teks. Hapus atau sembunyikan entri bila memang tidak ingin dipantau.
 */
export function MapTechDialog({ entry, onOpenChange }: MapTechDialogProps) {
  return (
    <Dialog open={entry !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        {entry && <MapTechBody key={entry.id} entry={entry} onClose={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}

function MapTechBody({ entry, onClose }: { entry: TechStackOut; onClose: () => void }) {
  const actions = useMonitorActions();
  const [search, setSearch] = useState(entry.name);
  const q = useDebounced(search.trim()).toLowerCase();
  const [picked, setPicked] = useState<{ ref: CatalogRef; label: string } | null>(null);
  const unmapped = entry.targets.length === 0;

  const taken = new Set(
    entry.targets.map((t) => refKey(t.kind === "vendor" ? { vendor_id: t.vendor_id ?? 0 } : { family_id: t.family_id ?? 0 })),
  );

  async function submit() {
    if (!picked) return;
    const ok = await actions.addTarget(entry.id, picked.ref);
    if (!ok) return;
    if (unmapped) onClose();
    else setPicked(null);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Map &quot;{entry.name}&quot; to the catalog</DialogTitle>
        <DialogDescription>Today it matches CVEs by name only. Pick the product it really is.</DialogDescription>
      </DialogHeader>

      {!unmapped && (
        <div className="flex flex-col gap-2">
          <p className="text-xs font-semibold">Current targets</p>
          <ul className="flex flex-wrap gap-2">
            {entry.targets.map((t) => (
              <li key={t.id} className="inline-flex items-center gap-1 rounded-lg bg-surface py-1 pr-1 pl-2.5 text-xs">
                {targetLabel(t)}
                <button
                  type="button"
                  aria-label={`Remove ${targetLabel(t)}`}
                  disabled={actions.busy || entry.targets.length <= 1}
                  title={entry.targets.length <= 1 ? "The last target cannot be removed" : undefined}
                  className="inline-flex size-6 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-panel hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() => void actions.removeTarget(entry.id, t.id)}
                >
                  <XIcon className="size-3.5" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <SearchInput value={search} onChange={setSearch} placeholder="Search vendor or product" aria-label="Search the catalog" />
      <CatalogPicker q={q} value={picked?.ref ?? null} onChange={(ref, label) => setPicked({ ref, label })} taken={taken} />

      <DialogFooter>
        <Button variant="ghost" onClick={onClose} disabled={actions.busy}>
          {unmapped ? "Cancel" : "Done"}
        </Button>
        <Button disabled={!picked} loading={actions.busy} onClick={() => void submit()}>
          {picked ? `Map to ${picked.label}` : "Map to catalog"}
        </Button>
      </DialogFooter>
    </>
  );
}
