import { cn } from "@/lib/utils";

/** Lencana "V" brand. Dipakai sidebar, login, 404 dan halaman error supaya satu bentuk saja. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid size-10 shrink-0 place-items-center rounded-full bg-primary font-heading text-lg font-bold text-primary-foreground shadow-sm",
        className,
      )}
    >
      V
    </span>
  );
}
