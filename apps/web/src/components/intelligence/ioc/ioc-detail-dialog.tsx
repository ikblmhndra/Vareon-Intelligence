"use client";

import { IocDetailBody, type IocTarget } from "@/components/intelligence/ioc/ioc-detail-body";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export type { IocTarget };

interface IocDetailDialogProps {
  target: IocTarget | null;
  onClose: () => void;
  onDeleted: () => void;
  /** Cache milik pemanggil yang ikut berubah (mis. daftar indikator entity). */
  onChanged?: () => void;
}

/** Pembungkus tipis `IocDetailBody` untuk tab Indicators di halaman entity: isinya identik dengan panel
 * kanan halaman IOC (spec 2b 6.9, D23), hanya bingkainya dialog. Fokus kembali ke pemicu (bawaan Base UI). */
export function IocDetailDialog({ target, onClose, onDeleted, onChanged }: IocDetailDialogProps) {
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] w-full max-w-2xl overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="sr-only">Indicator detail</DialogTitle>
          <DialogDescription className="sr-only">Enrichment, threat actors, sources, marking and analyst actions for this indicator.</DialogDescription>
        </DialogHeader>
        {target && (
          <IocDetailBody
            key={`${target.type}:${target.value}`}
            target={target}
            layout="dialog"
            onChanged={() => onChanged?.()}
            onDeleted={onDeleted}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
