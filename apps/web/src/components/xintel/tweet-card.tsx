import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Chip } from "@/components/ui/chip";
import type { components } from "@/lib/api/schema";
import { safeHttpUrl } from "@/lib/recap/quality";
import { fmtAgo, fmtDateTime } from "@/lib/format";

type Tweet = components["schemas"]["TweetOut"];

const CHIP_CAP = 6;
const followersFmt = new Intl.NumberFormat("en", { notation: "compact" });

/** Confidence bilangan bulat (C1): insiden terkonfirmasi memakai `incident_confidence`, selain itu `confidence`. */
export function tweetConfidence(t: Tweet): number | null {
  const v = t.confirmed_incident && t.incident_confidence != null ? t.incident_confidence : t.confidence;
  return v == null ? null : Math.round(v);
}

interface CardChip {
  key: string;
  node: React.ReactNode;
}

/** Baris chip kartu, urutan dan batas sesuai spec 6.1; sisanya "+n" dan tetap ada di dialog. */
function chipRow(t: Tweet): CardChip[] {
  const out: CardChip[] = [];
  const flag = (key: string, text: string, className?: string) =>
    out.push({
      key,
      node: (
        <Chip kind="flag" value={text} className={className ?? "normal-case"}>
          {text}
        </Chip>
      ),
    });
  if (t.victim_name) flag("victim", `victim · ${t.victim_name}`);
  (t.mentioned_group ?? []).slice(0, 2).forEach((g) => flag(`grp-${g}`, g));
  if ((t.databreach_list ?? []).length > 0) {
    const country = (t.victim_countries ?? [])[0];
    flag("breach", country ? `${country} / data breach` : "data breach");
  }
  (t.cve_list ?? []).slice(0, 2).forEach((c) => flag(`cve-${c}`, c.toUpperCase(), "font-code"));
  (t.industries_impacted ?? []).slice(0, 2).forEach((i) => flag(`ind-${i}`, i));
  if (t.apac_indicator) flag("apac", "APAC", "");
  if (t.ot_status) flag("ot", "OT", "");
  if ((t.zero_day_list ?? []).length > 0)
    out.push({ key: "0day", node: <Chip kind="severity" value="critical">0-DAY</Chip> });
  if (t.report_status) flag("report", "REPORT", "");
  return out;
}

/** Port `renderTweetCard()`. Satu `<button>` untuk membuka dialog (hanya teks dan chip di dalamnya);
 * media dan "Open on X" adalah tautan saudara, bukan elemen interaktif bersarang. */
export function TweetCard({ tweet: t, onOpen }: { tweet: Tweet; onOpen: () => void }) {
  const cleanText = t.text.replace(/https:\/\/t\.co\/\S+/g, "").trim();
  const postUrl = safeHttpUrl(t.url);
  const media = (t.media_urls ?? []).flatMap((u) => safeHttpUrl(u) ?? []).slice(0, 2);
  const chips = chipRow(t);
  const confidence = tweetConfidence(t);
  const name = t.author_name || t.author_username;

  return (
    <article className="surface-raised rounded-2xl p-5">
      <div className="flex items-start gap-3">
        <Avatar className="size-10 shrink-0">
          <AvatarImage src={t.author_avatar || undefined} alt="" />
          <AvatarFallback className="text-muted-foreground">{name.charAt(0).toUpperCase()}</AvatarFallback>
        </Avatar>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-foreground">{name}</p>
          <p className="text-xs text-muted-foreground">
            <span className="font-code">@{t.author_username}</span>
            {t.author_followers > 0 && ` · ${followersFmt.format(t.author_followers)} followers`}
            {" · "}
            <span title={fmtDateTime(t.posted_on)}>{fmtAgo(t.posted_on)}</span>
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
          {t.confirmed_incident && (
            <Chip kind="status" value="action">
              CONFIRMED INCIDENT
            </Chip>
          )}
          {confidence !== null && (
            <Chip kind="flag" value="confidence" className="normal-case">
              confidence <span className="ml-1 font-code">{confidence}</span>
            </Chip>
          )}
        </div>
      </div>

      <button
        type="button"
        onClick={onOpen}
        className="mt-3 block w-full rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <span className="line-clamp-4 block text-sm leading-relaxed break-words text-foreground">{cleanText}</span>
        {chips.length > 0 && (
          <span className="mt-3 flex flex-wrap items-center gap-1.5">
            {chips.slice(0, CHIP_CAP).map((c) => (
              <span key={c.key}>{c.node}</span>
            ))}
            {chips.length > CHIP_CAP && (
              <span className="font-code text-2xs text-muted-foreground">+{chips.length - CHIP_CAP}</span>
            )}
          </span>
        )}
      </button>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {media.map((url) => {
          const img = (
            // eslint-disable-next-line @next/next/no-img-element -- URL eksternal dari X CDN, bukan aset lokal
            <img src={url} alt="Post media" className="h-[72px] w-auto rounded-xl border border-border object-cover" />
          );
          return postUrl ? (
            <a
              key={url}
              href={postUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              {img}
            </a>
          ) : (
            <span key={url}>{img}</span>
          );
        })}
        {postUrl && (
          <a
            href={postUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto rounded text-xs font-semibold text-primary-text underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Open on X ↗
          </a>
        )}
      </div>
    </article>
  );
}
