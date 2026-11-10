"use client";

import { TriangleAlertIcon } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  /** Baris peringatan tambahan (mis. "ini overwrite data lama"). */
  warning?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Kolom catatan opsional (mis. alasan menutup RFI); nilainya diteruskan ke `onConfirm(note)`. */
  note?: { label: string; placeholder?: string; maxLength: number };
  /** `danger` = tombol konfirmasi `variant="destructive"`. */
  tone?: "default" | "danger";
  /** Bila diberikan, dialog TIDAK menutup sendiri saat konfirmasi: pemanggil menutupnya setelah aksi
   * selesai, dan tombol menampilkan status memuat. Tanpa ini perilaku lama (tutup lalu `onConfirm`). */
  confirmLoading?: boolean;
  /** Varian tombol batal; baku `outline`. Dialog redesign 2b memakai `ghost` (spec 6.11). */
  cancelVariant?: "outline" | "ghost";
  /** Ke mana fokus kembali setelah dialog tertutup (mis. baris terpilih di tabel IOC, yang tetap ada
   * walau tombol pemicu di panel hilang setelah aksi). Tanpa ini: elemen pemicu, perilaku bawaan Base UI. */
  finalFocus?: () => HTMLElement | null;
  onConfirm: (note?: string) => void;
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
  note,
  tone = "default",
  confirmLoading,
  cancelVariant = "outline",
  finalFocus,
  onConfirm,
}: ConfirmDialogProps) {
  const [noteText, setNoteText] = useState("");
  // Catatan dikosongkan setiap `open` berubah (bukan hanya lewat handler): pada mode `confirmLoading`
  // induk menutup dialog dengan membalik `open`, jadi handler tidak jalan. Pola "sesuaikan state saat render".
  const [prevOpen, setPrevOpen] = useState(open);
  if (prevOpen !== open) {
    setPrevOpen(open);
    setNoteText("");
  }
  function handleOpenChange(next: boolean) {
    // Selama permintaan berjalan, Esc/klik di luar tidak boleh menutup dialog.
    if (confirmLoading && !next) return;
    onOpenChange(next);
  }
  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-sm" finalFocus={finalFocus ? () => finalFocus() ?? true : undefined}>
        <DialogHeader>
          <DialogTitle className="font-heading">{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        {warning && (
          <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 font-mono text-xs text-warning-text">
            <TriangleAlertIcon aria-hidden /> {warning}
          </p>
        )}
        {note && (
          <div className="space-y-1.5">
            <label htmlFor="confirm-dialog-note" className="text-sm font-medium">
              {note.label}
            </label>
            <Textarea
              id="confirm-dialog-note"
              value={noteText}
              maxLength={note.maxLength}
              placeholder={note.placeholder}
              onChange={(e) => setNoteText(e.target.value)}
            />
            <p className="text-right text-2xs text-muted-foreground">
              {noteText.length} / {note.maxLength}
            </p>
          </div>
        )}
        <DialogFooter>
          <Button variant={cancelVariant} disabled={confirmLoading} onClick={() => handleOpenChange(false)}>
            {cancelLabel}
          </Button>
          <Button
            variant={tone === "danger" ? "destructive" : "default"}
            loading={confirmLoading}
            onClick={() => {
              const text = noteText.trim();
              if (confirmLoading === undefined) handleOpenChange(false);
              onConfirm(note ? text : undefined);
            }}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
