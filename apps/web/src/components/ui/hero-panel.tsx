import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Kelas tautan di atas permukaan hero: aksen terang + cincin fokus yang offset-nya memakai warna hero
 * (offset `background` akan tampak sebagai bingkai putih di atas burgundy). */
export const heroLinkClass =
  "text-hero-accent underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-hero rounded-sm";

interface HeroPanelProps {
  kicker?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  className?: string;
}

/** Panel burgundy (`bg-hero`) untuk sinyal terkuat / sel terpilih / pratinjau entitas. Warna tetap di kedua
 * tema, jadi semua teks memakai token `hero-*`, bukan token tema biasa. */
export function HeroPanel({ kicker, title, children, footer, className }: HeroPanelProps) {
  return (
    <section className={cn("flex flex-col gap-3 rounded-lg bg-hero p-5 text-hero-foreground", className)}>
      {kicker && (
        <p className="text-2xs font-bold tracking-[0.12em] text-hero-eyebrow uppercase">{kicker}</p>
      )}
      <h2 className="font-heading text-xl leading-snug font-semibold">{title}</h2>
      {children && <div className="text-sm text-hero-muted">{children}</div>}
      {footer && <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs">{footer}</div>}
    </section>
  );
}
