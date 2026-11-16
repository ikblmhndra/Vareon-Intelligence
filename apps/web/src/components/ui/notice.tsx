import type { ReactNode } from "react";
import { Loader2Icon } from "lucide-react";

import { cn } from "@/lib/utils";

// Kelas ditulis utuh supaya Tailwind menemukannya; teks di atas tint memakai `text-X-text`.
const TONE = {
  neutral: { surface: "bg-foreground/10", dot: "bg-foreground", title: "text-foreground" },
  warning: { surface: "bg-warning/10", dot: "bg-warning", title: "text-warning-text" },
  info: { surface: "bg-info/10", dot: "bg-info", title: "text-info-text" },
  destructive: { surface: "bg-destructive/10", dot: "bg-destructive", title: "text-destructive-text" },
} as const;

interface NoticeProps {
  tone?: keyof typeof TONE;
  busy?: boolean;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}

/** Banner status inline (bukan kartu kosong): titik berwarna, atau spinner saat `busy`, judul, isi, dan aksi opsional. */
export function Notice({ tone = "neutral", busy, title, children, action, className }: NoticeProps) {
  const t = TONE[tone];
  return (
    <div
      role="status"
      className={cn("flex items-start gap-3 rounded-lg px-4 py-3 text-sm", t.surface, className)}
    >
      {busy ? (
        <Loader2Icon aria-hidden="true" className={cn("mt-0.5 size-4 shrink-0 animate-spin", t.title)} />
      ) : (
        <span aria-hidden="true" className={cn("mt-1.5 size-2 shrink-0 rounded-full", t.dot)} />
      )}
      <div className="min-w-0 flex-1">
        <p className={cn("font-semibold", t.title)}>{title}</p>
        {children && <div className="mt-0.5 text-xs text-muted-foreground">{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
