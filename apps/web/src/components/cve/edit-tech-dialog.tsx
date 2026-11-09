"use client";

import { useId, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/lib/api/client";
import { EXPOSURE_LABEL, HOSTING_LABEL, useMonitorActions, type TechStackOut } from "@/lib/cve/catalog";

/** Dua Select Exposure + Hosting (D15), dipakai Edit, Add custom dan Add from catalog. */
export function ExposureHostingFields({
  exposure,
  hosting,
  onExposure,
  onHosting,
}: {
  exposure: string;
  hosting: string;
  onExposure: (v: string) => void;
  onHosting: (v: string) => void;
}) {
  const uid = useId();
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Exposure" htmlFor={`${uid}-exposure`}>
        <Select items={EXPOSURE_LABEL} value={exposure} onValueChange={(v) => v != null && onExposure(v)}>
          <SelectTrigger id={`${uid}-exposure`} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(EXPOSURE_LABEL).map(([v, l]) => (
              <SelectItem key={v} value={v}>
                {l}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label="Hosting" htmlFor={`${uid}-hosting`}>
        <Select items={HOSTING_LABEL} value={hosting} onValueChange={(v) => v != null && onHosting(v)}>
          <SelectTrigger id={`${uid}-hosting`} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(HOSTING_LABEL).map(([v, l]) => (
              <SelectItem key={v} value={v}>
                {l}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
    </div>
  );
}

interface EditTechDialogProps {
  entry: TechStackOut | null;
  onOpenChange: (open: boolean) => void;
}

/** Dialog "Edit {entry}": ubah Exposure dan Hosting (D15). Hanya field yang berubah yang dikirim. */
export function EditTechDialog({ entry, onOpenChange }: EditTechDialogProps) {
  return (
    <Dialog open={entry !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        {entry && <EditBody key={entry.id} entry={entry} onClose={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}

function EditBody({ entry, onClose }: { entry: TechStackOut; onClose: () => void }) {
  const { invalidate } = useMonitorActions();
  const [exposure, setExposure] = useState(entry.exposure);
  const [hosting, setHosting] = useState(entry.hosting_type);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      if (exposure !== entry.exposure) {
        const { error } = await api.PATCH("/api/techstack/{tech_id}/exposure", {
          params: { path: { tech_id: entry.id } },
          body: { exposure },
        });
        if (error) throw new Error("Exposure update failed");
      }
      if (hosting !== entry.hosting_type) {
        const { error } = await api.PATCH("/api/techstack/{tech_id}/hosting", {
          params: { path: { tech_id: entry.id } },
          body: { hosting_type: hosting },
        });
        if (error) throw new Error("Hosting update failed");
      }
      toast.success(`Saved ${entry.name}`);
      invalidate();
      onClose();
    } catch (e) {
      toast.error((e as Error).message);
      invalidate();
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Edit {entry.name}</DialogTitle>
        <DialogDescription>Public, internet-facing entries raise a CVE&apos;s adjusted risk.</DialogDescription>
      </DialogHeader>
      <ExposureHostingFields exposure={exposure} hosting={hosting} onExposure={setExposure} onHosting={setHosting} />
      <DialogFooter>
        <Button variant="ghost" onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button loading={saving} onClick={() => void save()}>
          Save
        </Button>
      </DialogFooter>
    </>
  );
}
