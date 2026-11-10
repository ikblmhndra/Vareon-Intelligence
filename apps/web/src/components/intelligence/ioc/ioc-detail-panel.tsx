"use client";

import { IocDetailBody, type IocTarget } from "@/components/intelligence/ioc/ioc-detail-body";
import { StatePanel } from "@/components/ui/state-panel";

interface IocDetailPanelProps {
  target: IocTarget | null;
  /** Setelah aksi apa pun di panel (mis. halaman menyematkan pilihan supaya IOC yang keluar dari daftar tetap tampil). */
  onChanged?: () => void;
  /** Setelah hapus permanen: halaman mengosongkan pilihan. */
  onDeleted?: () => void;
  /** Fokus kembali ke baris terpilih setelah dialog hapus/remove tertutup. */
  returnFocus?: () => HTMLElement | null;
}

/** Panel kanan halaman IOC (spec 2b 6.9): menggantikan dialog detail lama. `key` per target supaya draf
 * (input TA, peringatan FP sumber) tidak terbawa ke IOC lain. */
export function IocDetailPanel({ target, onChanged, onDeleted, returnFocus }: IocDetailPanelProps) {
  if (!target)
    return <StatePanel variant="empty" title="No indicator selected" description="Select a row to see its enrichment, sources and actions." />;
  return (
    <IocDetailBody
      key={`${target.type}:${target.value}`}
      target={target}
      layout="panel"
      onChanged={() => onChanged?.()}
      onDeleted={onDeleted}
      returnFocus={returnFocus}
    />
  );
}
