"use client";

import { TriangleAlertIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  /** Baris peringatan tambahan (mis. "ini overwrite data lama"). */
  warning?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
}

/**
 * Modal konfirmasi generik -- gantiin pola `.modal-overlay#*-confirm-overlay`
 * manual yang di-duplikasi tiap tab di app lama (mis. `recap-confirm-overlay`
 * di `tab_recap.html`). Dideklarasikan pas dibutuhkan beneran pertama kali
 * (Recap "GENERATE"/"FORCE REGEN"), sesuai catatan deferred Grup A --
 * daripada desain API generik tanpa use-case nyata di tangan.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  warning,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="font-heading">{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        {warning && (
          <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 font-mono text-xs text-warning-text">
            <TriangleAlertIcon aria-hidden /> {warning}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {cancelLabel}
          </Button>
          <Button
            onClick={() => {
              onOpenChange(false);
              onConfirm();
            }}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
