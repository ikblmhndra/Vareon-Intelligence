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
export function ArticleCard({ article: a, onClick }: { article: Article; onClick: () => void }) {
  const tags = [...(a.impacted_industries ?? []).slice(0, 2), ...(a.threat_actors ?? []).slice(0, 1)];
  const iocCount = Object.values(a.iocs ?? {}).reduce<number>(
    (sum, v) => sum + (Array.isArray(v) ? v.length : 0),
    0,
  );

  return (
    <div
      onClick={onClick}
      className="cursor-pointer rounded-xl border border-border bg-background px-3 py-2.5 transition-colors hover:border-ring/50"
    >
      <div className="text-sm leading-snug text-foreground">{a.title}</div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {tags.map((t) => (
          <Badge key={t} variant="outline" className="text-xs text-muted-foreground">
            {t}
          </Badge>
        ))}
        {iocCount > 0 && (
          <Badge
            variant="outline"
            title={`${iocCount} indicator(s) of compromise extracted`}
            className="border-warning/30 bg-warning/10 font-mono text-xs text-warning-text"
          >
            IOC:{iocCount}
          </Badge>
        )}
        <span className="ml-auto text-xs text-muted-foreground">{timeAgo(a.posted_on)}</span>
        <span className="font-mono text-xs text-muted-foreground">{a.source}</span>
      </div>
    </div>
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
  return (
    <div
      className={cn(
        layout === "list" ? "flex flex-col gap-1.5" : "grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3",
      )}
    >
      {articles.map((a) => (
        <ArticleCard key={a.id} article={a} onClick={() => onSelect(a)} />
      ))}
    </div>
  );
}
