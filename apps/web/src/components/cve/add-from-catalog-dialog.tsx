"use client";

import { useState } from "react";

import { CatalogPicker } from "@/components/cve/catalog-picker";
import { ExposureHostingFields } from "@/components/cve/edit-tech-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { SearchInput } from "@/components/ui/search-input";
import { useDebounced, useMonitorActions, type CatalogRef } from "@/lib/cve/catalog";

interface AddFromCatalogDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Dialog "Add from catalog": pilih produk/vendor katalog yang belum dipantau, set Exposure + Hosting. */
export function AddFromCatalogDialog({ open, onOpenChange }: AddFromCatalogDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <AddFromCatalogBody onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function AddFromCatalogBody({ onClose }: { onClose: () => void }) {
  const actions = useMonitorActions();
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim()).toLowerCase();
  const [picked, setPicked] = useState<{ ref: CatalogRef; label: string } | null>(null);
  const [exposure, setExposure] = useState("internal");
  const [hosting, setHosting] = useState("on_prem");

  async function submit() {
    if (!picked) return;
    if (await actions.monitor(picked.ref, undefined, { exposure, hosting_type: hosting })) onClose();
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Add from catalog</DialogTitle>
        <DialogDescription>
          Pick the product to watch, or a whole vendor. CVEs are matched by the product&apos;s identity, not by name text.
        </DialogDescription>
      </DialogHeader>
      <SearchInput value={search} onChange={setSearch} placeholder="Search vendor or product" aria-label="Search the catalog" />
      <CatalogPicker q={q} value={picked?.ref ?? null} onChange={(ref, label) => setPicked({ ref, label })} disableMonitored />
      <ExposureHostingFields exposure={exposure} hosting={hosting} onExposure={setExposure} onHosting={setHosting} />
      <DialogFooter>
        <Button variant="ghost" onClick={onClose} disabled={actions.busy}>
          Cancel
        </Button>
        <Button disabled={!picked} loading={actions.busy} onClick={() => void submit()}>
          Add to monitored tech
        </Button>
      </DialogFooter>
    </>
  );
}
