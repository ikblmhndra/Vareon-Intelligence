"use client";

import { useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { api } from "@/lib/api/client";
import type { IocFeedbackResponse } from "@/lib/api/loose-types";

interface IocRemoveDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `value` = teks yang tampil di judul (pemanggil sudah men-defang-nya); `id` dipakai untuk POST. */
  ioc: { id: number; value: string };
  /** Dipanggil SETELAH dialog menutup dan verdict "fp" tersimpan; pemanggil menangani toast, peringatan
   * FP sumber, dan invalidasi cache miliknya. */
  onDone: (res: IocFeedbackResponse) => void;
  /** Fokus setelah dialog menutup (baris terpilih di tabel IOC); tanpa ini kembali ke pemicunya. */
  finalFocus?: () => HTMLElement | null;
}

/** Dialog "Remove from feeds" (spec 2b 6.9), dipakai bersama panel detail IOC dan antrean FP Exec supaya copy
 * dan perilakunya satu. Gagal: dialog tetap terbuka dan menampilkan galat di dalamnya (bukan toast yang
 * dialognya sudah hilang), jadi analis bisa mencoba lagi tanpa mengetik ulang catatan. */
export function IocRemoveDialog({ open, onOpenChange, ioc, onDone, finalFocus }: IocRemoveDialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Galat lama dibuang tiap dialog dibuka/ditutup ulang (pola "sesuaikan state saat render").
  const [prevOpen, setPrevOpen] = useState(open);
  if (prevOpen !== open) {
    setPrevOpen(open);
    setError(null);
  }

  async function remove(note?: string) {
    setBusy(true);
    setError(null);
    try {
      const { data, error: err, response } = await api.POST("/api/iocs/{ioc_id}/feedback", {
        params: { path: { ioc_id: ioc.id } },
        body: { verdict: "fp", note: note || null },
      });
      // Body kosong pada 5xx: `error` undefined tetapi `response.ok` false.
      if (err || !response.ok || data === undefined) throw new Error(err ? JSON.stringify(err) : `HTTP ${response.status}`);
      onOpenChange(false);
      onDone(data as unknown as IocFeedbackResponse);
    } catch (e) {
      setError(`Feedback failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Remove ${ioc.value} from feeds?`}
      description="It stops appearing in STIX and CSV exports for every client. Analysts can restore it with TP."
      warning={error ?? undefined}
      note={{ label: "Note", placeholder: "Optional: why this is a false positive", maxLength: 2000 }}
      confirmLabel="Remove from feeds"
      cancelVariant="ghost"
      tone="danger"
      confirmLoading={busy}
      finalFocus={finalFocus}
      onConfirm={(note) => void remove(note)}
    />
  );
}
