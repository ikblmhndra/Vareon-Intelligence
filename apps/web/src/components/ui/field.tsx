import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Nilai `aria-describedby` untuk kontrol di dalam `Field` (pasangkan dengan `aria-invalid={!!error}`). */
export function fieldDescribedBy(
  id: string,
  { hint, error }: { hint?: string; error?: string },
): string | undefined {
  const ids = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean);
  return ids.length ? ids.join(" ") : undefined;
}

interface FieldProps {
  label: string;
  htmlFor: string;
  hint?: string;
  error?: string;
  children: ReactNode;
  className?: string;
}

/** Label + kontrol + petunjuk/galat. Kontrol (anak) harus ber-`id={htmlFor}` dan memakai
 * `aria-describedby={fieldDescribedBy(...)}`. Galat memakai `role="alert"`. */
export function Field({ label, htmlFor, hint, error, children, className }: FieldProps) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={htmlFor} className="text-xs font-semibold text-foreground">
        {label}
      </label>
      {children}
      {hint && (
        <p id={`${htmlFor}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${htmlFor}-error`} role="alert" className="text-xs text-destructive-text">
          {error}
        </p>
      )}
    </div>
  );
}
