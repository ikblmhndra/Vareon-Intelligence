"use client";

import { TriangleAlertIcon } from "lucide-react";
import { useState } from "react";

import type { RecapKind } from "@/lib/api/loose-types";
import { formatRange, mondayOf, sundayOf } from "@/lib/recap/period";
import { Button } from "@/components/ui/button";
import { DateField } from "@/components/ui/date-field";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { SegmentedControl } from "@/components/ui/segmented-control";

const KIND_OPTIONS = [
  { value: "weekly", label: "Week" },
  { value: "daily", label: "Day" },
] as const;

export interface RecapGenerateRequest {
  kind: RecapKind;
  date: string;
  force: boolean;
}

interface RecapGenerateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultKind: RecapKind;
  defaultDate: string;
  /** Kunci `{kind}:{date}` recap yang sudah tersimpan (dari daftar history): menentukan judul,
   * peringatan timpa, dan `force`. */
  existing: ReadonlySet<string>;
  pending: boolean;
  error?: string | null;
  onConfirm: (req: RecapGenerateRequest) => void;
}

/**
 * Dialog buat/ulang recap. Dibangun di atas `Dialog` (bukan `ConfirmDialog`) karena memuat form.
 * Pekan yang Minggunya belum lewat di UTC ditolak di sini (tombol mati + pesan) selain di API (400):
 * recap setengah pekan tidak boleh tersimpan sebagai recap pekan itu.
 */
export function RecapGenerateDialog(props: RecapGenerateDialogProps) {
  const { open, onOpenChange, defaultKind, defaultDate, existing, pending, error, onConfirm } = props;
  const [kind, setKind] = useState<RecapKind>(defaultKind);
  const [date, setDate] = useState(defaultDate);
  // Jangkar "hari ini" = state sekali jalan, bukan `new Date()` di render (render harus murni).
  const [todayIso] = useState(() => new Date().toISOString().slice(0, 10));
  // Isi form disetel ulang tiap dialog dibuka: pola "sesuaikan state saat render".
  const [prevOpen, setPrevOpen] = useState(open);
  if (prevOpen !== open) {
    setPrevOpen(open);
    if (open) {
      setKind(defaultKind);
      setDate(defaultDate);
    }
  }

  const weekly = kind === "weekly";
  const target = weekly ? mondayOf(date) : date;
  const overwrite = !!target && existing.has(`${kind}:${target}`);
  const unfinished = weekly && !!target && sundayOf(target) >= todayIso;
  const noun = weekly ? "week" : "date";

  return (
    <Dialog open={open} onOpenChange={(next) => (pending && !next ? undefined : onOpenChange(next))}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{overwrite ? "Regenerate recap" : "Generate recap"}</DialogTitle>
          <DialogDescription>This calls the LLM and may take 10-30 seconds.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <SegmentedControl
            options={KIND_OPTIONS}
            value={kind}
            onChange={setKind}
            aria-label="Recap kind"
          />
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium">
              {weekly ? "Week of" : "Date"}
            </span>
            <DateField
              id="recap-gen-date"
              aria-label={weekly ? "Week of" : "Date"}
              value={target || null}
              onChange={(v) => setDate(v ?? "")}
            />
            {weekly && target && (
              <span className="font-code text-xs text-muted-foreground">
                {formatRange(target, sundayOf(target))} (Mon-Sun, UTC)
              </span>
            )}
          </div>
        </div>
        {overwrite && (
          <p className="rounded-md bg-warning/10 px-3 py-2 text-xs text-warning-text">
            <TriangleAlertIcon aria-hidden className="mr-1 inline size-3.5" />
            This overwrites the stored recap for this {noun}.
          </p>
        )}
        {unfinished && (
          <p role="alert" className="text-xs text-destructive-text">
            A week can only be generated after its Sunday has ended in UTC.
          </p>
        )}
        {error && (
          <p role="alert" className="text-xs text-destructive-text">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            loading={pending}
            disabled={!target || unfinished}
            onClick={() => onConfirm({ kind, date: target, force: overwrite })}
          >
            {overwrite ? "Regenerate" : "Generate"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
