import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface StatePanelProps {
  variant: "empty" | "loading" | "error" | "no-access";
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

/** Blok tengah untuk keadaan kosong/memuat/galat/tanpa-akses. `loading` = `role=status` + spinner;
 * `error` = `role=alert`. */
export function StatePanel({ variant, title, description, action, className }: StatePanelProps) {
  const role = variant === "loading" ? "status" : variant === "error" ? "alert" : undefined;
  return (
    <div
      role={role}
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border px-6 py-12 text-center",
        className,
      )}
    >
      {variant === "loading" && (
        <span
          aria-hidden="true"
          className="size-5 animate-spin rounded-full border-2 border-border border-t-foreground"
        />
      )}
      <p
        className={cn(
          "text-sm font-semibold",
          variant === "error" ? "text-destructive-text" : "text-foreground",
        )}
      >
        {title}
      </p>
      {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
