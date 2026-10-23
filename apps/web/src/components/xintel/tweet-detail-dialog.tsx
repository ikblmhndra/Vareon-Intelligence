"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { components } from "@/lib/api/schema";
import { TweetBadges } from "@/components/xintel/tweet-badges";

type Tweet = components["schemas"]["TweetOut"];

const NEWSLETTER_QUEUE_KEY = "newsletter_queue";

function MetaRow({
  label,
  items,
  variant = "outline",
  mono,
}: {
  label: string;
  items?: string[];
  variant?: "outline";
  mono?: boolean;
}) {
  if (!items || !items.length) return null;
  return (
    <div>
      <div className="mb-1.5 text-sm font-semibold text-muted-foreground">
        {label}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((v) => (
          <Badge key={v} variant={variant} className={mono ? "font-mono text-xs" : "text-xs"}>
            {v}
          </Badge>
        ))}
      </div>
    </div>
  );
}

/**
 * Queue tweet buat Newsletter -- Grup H (`/newsletter`) belum dibangun,
 * jadi ini nulis ke `localStorage` SAMA PERSIS kontrak lama
 * (`queueTweetForNewsletter()`), forward-compatible: begitu Grup H ada,
 * dia baca key yang sama tanpa perlu migrasi data.
 */
function queueForNewsletter(t: Tweet): "queued" | "already" {
  const raw = localStorage.getItem(NEWSLETTER_QUEUE_KEY);
  const queue: Array<{ _id: string | number | null }> = raw ? JSON.parse(raw) : [];
  const id = t.tweet_id ?? t.id;
  if (queue.some((x) => x._id === id)) return "already";
  queue.push({
    _id: id,
    title: t.text.replace(/https:\/\/t\.co\/\S+/g, "").trim().slice(0, 120),
    source: t.author_username ? `@${t.author_username}` : "𝕏 Intel",
    posted_on: t.posted_on || "",
    url: t.url || "",
    _is_tweet: true,
  } as never);
  localStorage.setItem(NEWSLETTER_QUEUE_KEY, JSON.stringify(queue));
  return "queued";
}

/** Port `openXiModal()`/`_xiMetaRow()` -- detail tweet penuh. */
export function TweetDetailDialog({
  tweet,
  onOpenChange,
}: {
  tweet: Tweet | null;
  onOpenChange: (open: boolean) => void;
}) {
  const [queueLabel, setQueueLabel] = useState("+ Newsletter");

  if (!tweet) return null;
  const t = tweet;
  const cleanText = t.text.replace(/https:\/\/t\.co\/\S+/g, "").trim();
  const media = t.media_urls ?? [];
  const apacItems = [...(t.mentioned_apac_country ?? []), ...(t.mentioned_apac_people ?? [])];
  const countryRoleItems = [
    ...(t.victim_countries ?? []).map((c) => `${c} (victim)`),
    ...(t.actor_countries ?? []).map((c) => `${c} (origin)`),
  ];

  function handleQueue() {
    const result = queueForNewsletter(t);
    setQueueLabel(result === "already" ? "Already queued" : "Queued");
    setTimeout(() => setQueueLabel("+ Newsletter"), 1500);
  }

  return (
    <Dialog open={tweet !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="font-mono text-sm">@{t.author_username}</DialogTitle>
        </DialogHeader>

        <div className="flex items-start gap-3 border-b border-border pb-4">
          <Avatar size="lg">
            <AvatarImage src={t.author_avatar || undefined} alt={t.author_username} />
            <AvatarFallback className="text-muted-foreground">𝕏</AvatarFallback>
          </Avatar>
          <div className="flex-1">
            {/* nama/followers kosong untuk tweet dari jalur alert (X resmi): sembunyikan */}
            {t.author_name && (
              <div className="text-base font-bold text-foreground">{t.author_name}</div>
            )}
            <div className="font-mono text-xs text-muted-foreground">@{t.author_username}</div>
            {t.author_followers > 0 && (
              <div className="mt-0.5 text-xs text-muted-foreground">
                {t.author_followers.toLocaleString()} followers
              </div>
            )}
          </div>
          <div className="text-right font-mono text-xs text-muted-foreground">
            <div>{t.posted_on ? `${t.posted_on.slice(0, 16).replace("T", " ")} UTC` : "—"}</div>
            <div className="mt-0.5">lang: {t.lang || "—"}</div>
          </div>
        </div>

        <div className="border-b border-border py-3.5 text-sm leading-relaxed whitespace-pre-wrap text-foreground">
          {cleanText}
        </div>

        {media.length > 0 && (
          <div className="flex flex-col gap-2 border-b border-border py-3">
            {media.map((url) => (
              // eslint-disable-next-line @next/next/no-img-element -- URL eksternal dari X CDN
              <img
                key={url}
                src={url}
                alt=""
                className="max-w-full cursor-pointer rounded border border-border"
                onClick={() => window.open(url, "_blank")}
              />
            ))}
          </div>
        )}

        <div className="flex flex-col gap-3 pt-3.5">
          <div>
            <div className="mb-1.5 text-sm font-semibold text-muted-foreground">
              Signals
            </div>
            <div className="flex flex-wrap gap-1.5">
              <TweetBadges tweet={t} />
            </div>
          </div>

          <MetaRow label="Threat Groups" items={t.mentioned_group} />
          <MetaRow label="APAC Countries / People" items={apacItems} />
          <MetaRow label="CVEs Mentioned" items={t.cve_list} mono />
          <MetaRow label="Zero-Day Signals" items={t.zero_day_list} />
          <MetaRow label="Data Breach Signals" items={t.databreach_list} />
          <MetaRow label="Industries Impacted" items={t.industries_impacted} />
          <MetaRow label="Country Roles (LLM)" items={countryRoleItems} />

          {t.confirmed_incident && (
            <div>
              <div className="mb-1.5 text-sm font-semibold text-muted-foreground">
                Incident
              </div>
              <div className="flex flex-col gap-1 text-xs">
                {t.victim_name && (
                  <div>
                    <span className="text-muted-foreground">Victim:</span> {t.victim_name}
                  </div>
                )}
                {(t.incident_indicators ?? []).length > 0 && (
                  <div className="flex flex-wrap items-center gap-1">
                    <span className="text-muted-foreground">Indicators:</span>
                    {t.incident_indicators!.map((i) => (
                      <Badge key={i} variant="outline" className="text-xs">
                        {i}
                      </Badge>
                    ))}
                  </div>
                )}
                {t.incident_confidence != null && (
                  <div>
                    <span className="text-muted-foreground">Confidence:</span> {t.incident_confidence}%
                  </div>
                )}
              </div>
            </div>
          )}

          {t.confidence != null && (
            <div>
              <div className="mb-1.5 text-sm font-semibold text-muted-foreground">
                LLM Cyber Relevance
              </div>
              <div className="text-xs text-muted-foreground">
                Confidence: <span className="text-foreground">{t.confidence}%</span>
              </div>
            </div>
          )}

          <div className="border-t border-border pt-2 font-mono text-xs text-muted-foreground">
            fetched_at: {t.fetched_at ? `${t.fetched_at.slice(0, 19).replace("T", " ")} UTC` : "—"} · tweet_id:{" "}
            {t.tweet_id || "—"}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={handleQueue}>
            {queueLabel}
          </Button>
          <Button
            size="sm"
            nativeButton={false}
            render={<a href={t.url} target="_blank" rel="noopener noreferrer" />}
          >
            Open Tweet ↗
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
