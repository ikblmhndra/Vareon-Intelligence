import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface PageHeaderProps {
  title: string;
  description?: string;
  /** Slot kanan: filter/aksi tingkat halaman (mis. periode di Dashboard). */
  actions?: ReactNode;
  className?: string;
}

/** Header seragam semua halaman ber-shell: judul besar, deskripsi satu kalimat, dan slot aksi.
 * Ini satu-satunya `<h1>` di halamannya. Tanpa hook, jadi bisa dipakai di layout segmen
 * (Server Component) maupun di halaman klien. */
export function PageHeader({ title, description, actions, className }: PageHeaderProps) {
  return (
    <header className={cn("mb-8 flex flex-wrap items-end justify-between gap-x-8 gap-y-4", className)}>
      <div className="min-w-0 max-w-2xl">
        <span aria-hidden className="mb-3 block h-1 w-8 rounded-full bg-primary" />
        <h1 className="font-heading text-3xl leading-tight font-extrabold tracking-tight text-foreground sm:text-4xl">
          {title}
        </h1>
        {description && <p className="mt-2 max-w-[65ch] text-base text-muted-foreground">{description}</p>}
      </div>
      {actions}
    </header>
  );
}
