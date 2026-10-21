import { RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface PanelShellProps {
  title: string;
  count?: number;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  children: ReactNode;
  footer?: ReactNode;
  minHeight?: boolean;
}

/** Port `.news-panel`/`.panel-header` chrome (`newsroom.html`), dipakai
 * di semua 6 panel. Titik berwarna + cahaya di judul dulu dihapus: APAC dan Global memakai warna
 * yang sama (`--ring` = `--primary`), jadi titik itu tidak membedakan apa pun. */
export function PanelShell({
  title,
  count,
  onRefresh,
  isRefreshing,
  children,
  footer,
  minHeight,
}: PanelShellProps) {
  return (
    <div className={cn("flex flex-col overflow-hidden rounded-2xl surface-raised", minHeight && "min-h-[280px]")}>
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <h2 className="font-heading text-base font-semibold">{title}</h2>
        <div className="flex items-center gap-2">
          <span className="shrink-0 rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium whitespace-nowrap text-muted-foreground tabular-nums">
            {count === undefined ? "— items" : `${count.toLocaleString()} items`}
          </span>
          {onRefresh && (
            <Button size="icon-sm" variant="ghost" onClick={onRefresh} title="Refresh" aria-label={`Refresh ${title}`}>
              <RefreshCw className={cn(isRefreshing && "animate-spin")} />
            </Button>
          )}
        </div>
      </div>
      <div className="flex-1 p-3">{children}</div>
      {footer && <div className="border-t border-border p-2">{footer}</div>}
    </div>
  );
}

export function PanelLoading() {
  return (
    <div className="flex items-center justify-center py-10 text-xs text-muted-foreground">Loading…</div>
  );
}

export function PanelEmpty({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center gap-1 py-10 text-center text-xs text-muted-foreground">
      <span className="text-lg">◉</span>
      {message}
    </div>
  );
}

export function PanelError({ message = "Failed to load" }: { message?: string }) {
  return <div className="py-10 text-center text-xs text-destructive">{message}</div>;
}
