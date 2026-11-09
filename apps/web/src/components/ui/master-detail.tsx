import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface MasterDetailProps {
  list: ReactNode;
  detail: ReactNode;
  className?: string;
}

/** Tata letak master-detail: daftar + panel rincian; di bawah 1024 px menumpuk, di atasnya detail menempel (sticky). */
export function MasterDetail({ list, detail, className }: MasterDetailProps) {
  return (
    <div className={cn("grid gap-6 lg:grid-cols-[1.5fr_1fr]", className)}>
      <div className="min-w-0">{list}</div>
      <div className="min-w-0 lg:sticky lg:top-4 lg:self-start">{detail}</div>
    </div>
  );
}
