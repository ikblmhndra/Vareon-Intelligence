"use client";

import { useId, useState } from "react";
import { toast } from "sonner";

import { ExposureHostingFields } from "@/components/cve/edit-tech-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import type { TechStackActionResult } from "@/lib/api/loose-types";
import { useMonitorActions } from "@/lib/cve/catalog";

interface AddCustomTechDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Dialog "Add custom tech": entri tanpa target katalog (dicocokkan lewat teks nama sampai di-map). */
export function AddCustomTechDialog({ open, onOpenChange }: AddCustomTechDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <AddCustomBody onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function AddCustomBody({ onClose }: { onClose: () => void }) {
  const uid = useId();
  const { invalidate } = useMonitorActions();
  const [name, setName] = useState("");
  const [exposure, setExposure] = useState("internal");
  const [hosting, setHosting] = useState("on_prem");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const nameId = `${uid}-name`;

  async function submit() {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Enter a name.");
      return;
    }
    setSaving(true);
    try {
      const { data, error: err } = await api.POST("/api/techstack", {
        body: { name: trimmed, exposure, hosting_type: hosting },
      });
      if (err) throw new Error("Request failed");
      const d = data as unknown as TechStackActionResult;
      if (!d.success) {
        setError(d.reason === "duplicate" ? `${trimmed} already exists for this client.` : d.reason || "Request failed");
        return;
      }
      invalidate();
      toast.success("Added as custom (unmapped). Use Map to catalog for accurate matching.");
      onClose();
    } catch (e) {
      toast.error(`Add failed: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Add custom tech</DialogTitle>
        <DialogDescription>
          Matched by name text only until you map it to the catalog. Prefer Add from catalog when the product exists there.
        </DialogDescription>
      </DialogHeader>
      <Field label="Name" htmlFor={nameId} error={error}>
        <Input
          id={nameId}
          autoFocus
          value={name}
          placeholder="e.g. WordPress"
          onChange={(e) => {
            setName(e.target.value);
            setError("");
          }}
          onKeyDown={(e) => e.key === "Enter" && void submit()}
          aria-invalid={!!error}
          aria-describedby={fieldDescribedBy(nameId, { error })}
        />
      </Field>
      <ExposureHostingFields exposure={exposure} hosting={hosting} onExposure={setExposure} onHosting={setHosting} />
      <DialogFooter>
        <Button variant="ghost" onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button loading={saving} onClick={() => void submit()}>
          Add
        </Button>
      </DialogFooter>
    </>
  );
}
