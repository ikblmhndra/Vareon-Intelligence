"use client";

import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { FP_REASON_LABEL, type FpReason } from "@/lib/cve/labels";

const REASONS = Object.keys(FP_REASON_LABEL) as FpReason[];

/** Teks galat API (`detail` string atau daftar 422 FastAPI) -> satu kalimat untuk toast. */
function errorText(error: unknown): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => (d as { msg?: string }).msg ?? "").filter(Boolean).join("; ");
  return "Request failed";
}

interface FpDialogProps {
  cveIds: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone: () => void;
}

/** Dialog "Mark as false positive" (spec 2a 6.9): satu CVE (`cveIds.length === 1`) atau massal. Alasan
 * (enum) + catatan dipersist backend (D8). Catatan wajib bila alasan = Other (backend 422 kalau kosong). */
export function FpDialog({ cveIds, open, onOpenChange, onDone }: FpDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        {/* Body di dalam content: unmount saat tutup, jadi state form selalu bersih di bukaan berikut. */}
        <FpBody cveIds={cveIds} onClose={() => onOpenChange(false)} onDone={onDone} />
      </DialogContent>
    </Dialog>
  );
}

function FpBody({ cveIds, onClose, onDone }: { cveIds: string[]; onClose: () => void; onDone: () => void }) {
  const queryClient = useQueryClient();
  const uid = useId();
  const [reason, setReason] = useState<FpReason>("not_in_stack");
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState("");
  const [saving, setSaving] = useState(false);
  const single = cveIds.length === 1;

  async function submit() {
    // Kirim `note: ""` saat kosong: openapi-typescript menandai field ber-default sebagai wajib.
    const trimmed = note.trim();
    if (reason === "other" && !trimmed) {
      setNoteError("Add a note when the reason is Other.");
      return;
    }
    setSaving(true);
    try {
      const res = single
        ? await api.POST("/api/cve/{cve_id}/false-positive", {
            params: { path: { cve_id: cveIds[0] } },
            body: { reason, note: trimmed },
          })
        : await api.POST("/api/cve/bulk-false-positive", { body: { cve_ids: cveIds, reason, note: trimmed } });
      if (res.error) throw new Error(errorText(res.error));
      toast.success(single ? `${cveIds[0]} marked as a false positive` : `${cveIds.length} CVEs marked as false positives`);
      void queryClient.invalidateQueries({ queryKey: ["cve", "list"] });
      void queryClient.invalidateQueries({ queryKey: ["cve", "stats"] });
      onDone();
      onClose();
    } catch (e) {
      toast.error(`Mark false positive failed: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  const reasonId = `${uid}-reason`;
  const noteId = `${uid}-note`;
  return (
    <>
      <DialogHeader>
        <DialogTitle>
          {single ? (
            <>
              Mark <span className="font-code">{cveIds[0]}</span> as a false positive?
            </>
          ) : (
            `Mark ${cveIds.length} CVEs as false positives?`
          )}
        </DialogTitle>
        <DialogDescription>
          It leaves the CVEs tab and stops counting in the dashboard. You can restore it from the False positive tab.
        </DialogDescription>
      </DialogHeader>
      <Field label="Reason" htmlFor={reasonId}>
        <Select
          items={FP_REASON_LABEL}
          value={reason}
          onValueChange={(v) => {
            if (v == null) return;
            setReason(v as FpReason);
            setNoteError("");
          }}
        >
          <SelectTrigger id={reasonId} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {REASONS.map((r) => (
              <SelectItem key={r} value={r}>
                {FP_REASON_LABEL[r]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label={reason === "other" ? "Note (required)" : "Note (optional)"} htmlFor={noteId} error={noteError}>
        <Textarea
          id={noteId}
          rows={3}
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
            setNoteError("");
          }}
          aria-invalid={!!noteError}
          aria-describedby={fieldDescribedBy(noteId, { error: noteError })}
        />
      </Field>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button variant="destructive" loading={saving} onClick={() => void submit()}>
          Mark false positive
        </Button>
      </DialogFooter>
    </>
  );
}
