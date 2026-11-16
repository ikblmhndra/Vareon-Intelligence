import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface PageHeaderProps {
  title: string;
  description?: ReactNode;
  /** Slot kanan: filter/aksi tingkat halaman (mis. periode di Dashboard). */
  actions?: ReactNode;
  className?: string;
  /** Label kecil huruf kapital merah di atas judul (mis. nama seksi). */
  kicker?: string;
}

/** Header seragam semua halaman ber-shell: judul besar, deskripsi satu kalimat, dan slot aksi.
 * Ini satu-satunya `<h1>` di halamannya. Tanpa hook, jadi bisa dipakai di layout segmen
 * (Server Component) maupun di halaman klien. */
export function PageHeader({ title, description, actions, className, kicker }: PageHeaderProps) {
  return (
    <header className={cn("mb-6 flex flex-wrap items-end justify-between gap-x-8 gap-y-4 pt-6 pb-4", className)}>
      <div className="min-w-0 max-w-2xl">
        {kicker && (
          <p className="mb-2 text-[11px] font-bold tracking-[0.12em] text-primary uppercase">{kicker}</p>
        )}
        <h1 className="font-heading text-3xl leading-tight font-bold tracking-[-0.02em] text-foreground sm:text-[44px]">
          {title}
        </h1>
        {description && <div className="mt-2 max-w-[65ch] text-sm text-muted-foreground">{description}</div>}
      </div>
      {actions}
    </header>
  );
}
