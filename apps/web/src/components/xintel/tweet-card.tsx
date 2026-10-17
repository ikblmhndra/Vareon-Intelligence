import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import type { components } from "@/lib/api/schema";
import { TweetBadges } from "@/components/xintel/tweet-badges";

type Tweet = components["schemas"]["TweetOut"];

function timeAgo(iso: string): string {
  if (!iso) return "—";
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

/** Port `renderTweetCard()`. */
export function TweetCard({ tweet: t, onClick }: { tweet: Tweet; onClick: () => void }) {
  const cleanText = t.text.replace(/https:\/\/t\.co\/\S+/g, "").trim();
  const media = (t.media_urls ?? []).slice(0, 2);
  const industries = (t.industries_impacted ?? []).slice(0, 2);

  return (
    <div
      onClick={onClick}
      className="flex cursor-pointer gap-3 surface-raised rounded-2xl p-5 transition-shadow hover:ring-ring/40"
    >
      <Avatar className="size-9 shrink-0">
        <AvatarImage src={t.author_avatar || undefined} alt={t.author_username} />
        <AvatarFallback className="text-muted-foreground">𝕏</AvatarFallback>
      </Avatar>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-baseline gap-2">
          {/* tweet dari jalur alert (X resmi) tak membawa nama penulis: jangan render span kosong */}
          {t.author_name && (
            <span className="text-sm font-semibold text-foreground">{t.author_name}</span>
          )}
          <span className="font-mono text-xs text-muted-foreground">@{t.author_username}</span>
          <span className="ml-auto text-xs text-muted-foreground">{timeAgo(t.posted_on)}</span>
        </div>
        <div className="mb-2 line-clamp-4 text-sm leading-relaxed break-words">{cleanText}</div>
        {media.length > 0 && (
          <div className="mb-2 flex gap-1.5">
            {media.map((url) => (
              // eslint-disable-next-line @next/next/no-img-element -- URL eksternal dari X CDN, bukan aset lokal
              <img
                key={url}
                src={url}
                alt=""
                className="h-[72px] w-auto cursor-pointer rounded-xl border border-border object-cover"
                onClick={(e) => {
                  e.stopPropagation();
                  window.open(t.url, "_blank");
                }}
              />
            ))}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-1.5">
          <TweetBadges tweet={t} limit={2} />
          {industries.length > 0 && (
            <span className="ml-auto text-xs text-muted-foreground">{industries.join(" · ")}</span>
          )}
          <a
            href={t.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className={
              (industries.length > 0 ? "" : "ml-auto ") +
              "rounded border border-primary/30 px-2 py-0.5 font-mono text-xs text-primary no-underline"
            }
          >
            ↗ Open
          </a>
        </div>
      </div>
    </div>
  );
}
