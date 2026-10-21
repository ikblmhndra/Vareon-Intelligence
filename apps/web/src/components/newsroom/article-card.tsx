import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { components } from "@/lib/api/schema";

type Article = components["schemas"]["ArticleOut"];

function timeAgo(dateStr: string): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return dateStr;
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "1d ago";
  return `${days}d ago`;
}

/** Port `renderNewsItem()` (`render.js`). Admiralty reliability badge
 * (`_srScoreMap`) SENGAJA belum diport -- itu punya Source Reliability
 * (`/intelligence`, Grup G, belum dibangun), lihat catatan Grup D di
 * docs/PROGRESS.md. */
export function ArticleCard({
  article: a,
  onClick,
  variant,
}: {
  article: Article;
  onClick: () => void;
  /** `row` = baris di daftar vertikal (pemisah tipis, tanpa kotak); `tile` = kartu di grid. */
  variant: "row" | "tile";
}) {
  const tags = [...(a.impacted_industries ?? []).slice(0, 2), ...(a.threat_actors ?? []).slice(0, 1)];
  const iocCount = Object.values(a.iocs ?? {}).reduce<number>(
    (sum, v) => sum + (Array.isArray(v) ? v.length : 0),
    0,
  );

  // `<button>`, bukan `<div onClick>`: bisa difokus dan dibuka dengan Enter/Spasi (modal artikel).
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group block w-full cursor-pointer px-3 py-2.5 text-left transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
        variant === "row"
          ? "hover:bg-panel"
          : "rounded-xl border border-border bg-background hover:border-ring/50",
      )}
    >
      <span className="block text-sm leading-snug font-medium text-foreground group-hover:text-primary-text">
        {a.title}
      </span>
      <span className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span className="font-medium">{a.source}</span>
        <span>{timeAgo(a.posted_on)}</span>
        {iocCount > 0 && (
          <Badge
            variant="outline"
            title={`${iocCount} indicator(s) of compromise extracted`}
            className="border-warning/30 bg-warning/10 font-code text-xs text-warning-text"
          >
            IOC:{iocCount}
          </Badge>
        )}
      </span>
      {tags.length > 0 && (
        <span className="mt-1.5 flex flex-wrap gap-1.5">
          {tags.map((t) => (
            <Badge key={t} variant="outline" className="text-xs text-muted-foreground">
              {t}
            </Badge>
          ))}
        </span>
      )}
    </button>
  );
}

/** Bungkus list panel (APAC/Global/RW -- vertical stack) vs grid panel
 * (Local/Watchlist/Techstack -- `.indonesia-grid` lama, kartu berjajar). */
export function ArticleCollection({
  articles,
  layout,
  onSelect,
}: {
  articles: Article[];
  layout: "list" | "grid";
  onSelect: (a: Article) => void;
}) {
  const variant = layout === "list" ? "row" : "tile";
  return (
    <div
      className={cn(
        layout === "list" ? "flex flex-col divide-y divide-border/60" : "grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3",
      )}
    >
      {articles.map((a) => (
        <ArticleCard key={a.id} article={a} variant={variant} onClick={() => onSelect(a)} />
      ))}
    </div>
  );
}
