"use client";

import { useEffect, useRef, useState } from "react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { components } from "@/lib/api/schema";
import { fmtDateTime } from "@/lib/format";
import { safeHttpUrl } from "@/lib/recap/quality";

type Tweet = components["schemas"]["TweetOut"];

function MetaRow({ label, items, mono }: { label: string; items?: string[]; mono?: boolean }) {
  if (!items || !items.length) return null;
  return (
    <div>
      <h3 className="mb-1.5 text-sm font-semibold text-muted-foreground">{label}</h3>
      <div className="flex flex-wrap gap-1.5">
        {items.map((v) => (
          <Chip key={v} kind="flag" value={v} className={mono ? "font-code" : "normal-case"} />
        ))}
      </div>
    </div>
  );
}

const NEWSLETTER_QUEUE_KEY = "newsletter_queue";

/**
 * Antrean tweet untuk Newsletter: tulis ke key `newsletter_queue` dengan kontrak lama persis
 * (`_id` = tweet_id, `_is_tweet`). Sengaja TIDAK lewat `addToQueue`: id numerik/negatif palsu akan
 * ikut terkirim ke API draft sebagai id artikel. localStorage bisa tak tersedia atau berisi JSON rusak.
 */
function queueForNewsletter(t: Tweet): "queued" | "already" | "failed" {
  try {
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
  } catch {
    return "failed";
  }
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
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // Timer umpan balik dibersihkan saat dialog ditutup (tweet null) atau komponen dilepas.
  useEffect(() => () => clearTimeout(timer.current), [tweet]);

  if (!tweet) return null;
  const t = tweet;
  const cleanText = t.text.replace(/https:\/\/t\.co\/\S+/g, "").trim();
  const media = (t.media_urls ?? []).flatMap((u) => safeHttpUrl(u) ?? []);
  const postUrl = safeHttpUrl(t.url);
  const apacItems = [...(t.mentioned_apac_country ?? []), ...(t.mentioned_apac_people ?? [])];
  const countryRoleItems = [
    ...(t.victim_countries ?? []).map((c) => `${c} (victim)`),
    ...(t.actor_countries ?? []).map((c) => `${c} (origin)`),
  ];
  const hasSignals =
    t.confirmed_incident || t.apac_indicator || t.ot_status || t.report_status || (t.zero_day_list ?? []).length > 0;

  function handleQueue() {
    const result = queueForNewsletter(t);
    setQueueLabel(result === "already" ? "Already queued" : result === "failed" ? "Could not queue" : "Queued");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setQueueLabel("+ Newsletter"), 1500);
  }

  return (
    <Dialog open={tweet !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="font-code text-sm">@{t.author_username}</DialogTitle>
          <DialogDescription>
            {fmtDateTime(t.posted_on)} · lang {t.lang || "—"}
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-start gap-3 border-b border-border pb-4">
          <Avatar size="lg">
            <AvatarImage src={t.author_avatar || undefined} alt="" />
            <AvatarFallback className="text-muted-foreground">
              {(t.author_name || t.author_username).charAt(0).toUpperCase()}
            </AvatarFallback>
          </Avatar>
          <div className="flex-1">
            {/* nama/followers kosong untuk tweet dari jalur alert (X resmi): sembunyikan */}
            {t.author_name && <div className="text-base font-bold text-foreground">{t.author_name}</div>}
            <div className="font-code text-xs text-muted-foreground">@{t.author_username}</div>
            {t.author_followers > 0 && (
              <div className="mt-0.5 text-xs text-muted-foreground">{t.author_followers.toLocaleString()} followers</div>
            )}
          </div>
        </div>

        <div className="border-b border-border py-3.5 text-sm leading-relaxed whitespace-pre-wrap text-foreground">
          {cleanText}
        </div>

        {media.length > 0 && (
          <div className="flex flex-col gap-2 border-b border-border py-3">
            {media.map((url) => (
              <a key={url} href={url} target="_blank" rel="noopener noreferrer" className="rounded outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background">
                {/* eslint-disable-next-line @next/next/no-img-element -- URL eksternal dari X CDN */}
                <img src={url} alt="Post media" className="max-w-full rounded border border-border" />
              </a>
            ))}
          </div>
        )}

        <div className="flex flex-col gap-3 pt-3.5">
          {hasSignals && (
            <div>
              <h3 className="mb-1.5 text-sm font-semibold text-muted-foreground">Signals</h3>
              <div className="flex flex-wrap gap-1.5">
                {t.confirmed_incident && (
                  <Chip kind="status" value="action">
                    CONFIRMED INCIDENT
                  </Chip>
                )}
                {t.apac_indicator && <Chip kind="flag" value="APAC" />}
                {t.ot_status && <Chip kind="flag" value="OT" />}
                {(t.zero_day_list ?? []).length > 0 && (
                  <Chip kind="severity" value="critical">
                    0-DAY
                  </Chip>
                )}
                {t.report_status && <Chip kind="flag" value="REPORT" />}
              </div>
            </div>
          )}

          <MetaRow label="Threat Groups" items={t.mentioned_group} />
          <MetaRow label="APAC Countries / People" items={apacItems} />
          <MetaRow label="CVEs Mentioned" items={(t.cve_list ?? []).map((c) => c.toUpperCase())} mono />
          <MetaRow label="Zero-Day Signals" items={t.zero_day_list} />
          <MetaRow label="Data Breach Signals" items={t.databreach_list} />
          <MetaRow label="Industries Impacted" items={t.industries_impacted} />
          <MetaRow label="Country Roles (LLM)" items={countryRoleItems} />

          {t.confirmed_incident && (
            <div>
              <h3 className="mb-1.5 text-sm font-semibold text-muted-foreground">Incident</h3>
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
                      <Chip key={i} kind="flag" value={i} className="normal-case" />
                    ))}
                  </div>
                )}
                {t.incident_confidence != null && (
                  <div>
                    <span className="text-muted-foreground">Confidence:</span>{" "}
                    <span className="font-code">{Math.round(t.incident_confidence)}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {t.confidence != null && (
            <div>
              <h3 className="mb-1.5 text-sm font-semibold text-muted-foreground">LLM Cyber Relevance</h3>
              <div className="text-xs text-muted-foreground">
                Confidence: <span className="font-code text-foreground">{Math.round(t.confidence)}</span>
              </div>
            </div>
          )}

          <div className="border-t border-border pt-2 font-code text-xs text-muted-foreground">
            fetched_at: {t.fetched_at ? fmtDateTime(t.fetched_at) : "—"} · tweet_id: {t.tweet_id || "—"}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleQueue}>
            {queueLabel}
          </Button>
          {postUrl && (
            <Button nativeButton={false} render={<a href={postUrl} target="_blank" rel="noopener noreferrer" />}>
              Open on X ↗
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
