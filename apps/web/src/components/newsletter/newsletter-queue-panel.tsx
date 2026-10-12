"use client";

import type { ReactNode } from "react";
import { TriangleAlertIcon, XIcon } from "lucide-react";

import { DestinationMenu, ReasonChips } from "@/components/newsletter/article-parts";
import type { PoolEntry } from "@/components/newsletter/newsletter-composer-sections";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { NewsletterSourceHint } from "@/lib/api/loose-types";
import type { components } from "@/lib/api/schema";
import type { ComposerState, SlotKey } from "@/lib/newsletter/composer";
import type { QueueArticle } from "@/lib/newsletter/queue";

type Article = components["schemas"]["ArticleOut"];

interface Props {
  state: ComposerState;
  queue: QueueArticle[];
  /** Saran yang belum ditempatkan (dibuang dari composer, atau belum dipakai). */
  suggested: PoolEntry[];
  paywallHints: Record<string, NewsletterSourceHint>;
  onAssign: (slot: SlotKey, entry: PoolEntry) => void;
  onRemove: (articleId: number) => void;
  onClearAll: () => void;
}

/** Kolam artikel di luar composer, dua kelompok: "Suggested, not placed" (dari saran server,
 * dengan alasannya) dan "Queued Articles" (tombol "+ Newsletter" di Newsroom, lewat localStorage
 * key `newsletter_queue`, lihat `lib/newsletter/queue.ts`, kontraknya tidak berubah). Port panel
 * kiri `newsletter.html:287-305`; kelompok saran baru (ROADMAP #22, PR 9). */
export function NewsletterQueuePanel({ state, queue, suggested, paywallHints, onAssign, onRemove, onClearAll }: Props) {
  const empty = queue.length === 0 && suggested.length === 0;
  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 flex items-center justify-between border-b border-border pb-3">
        <div className="text-base font-semibold text-foreground">Articles</div>
        <span className="font-mono text-xs text-primary">
          {suggested.length + queue.length} available
        </span>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto">
        {empty && (
          <p className="py-10 text-center text-xs text-muted-foreground">
            Nothing waiting — go to Newsroom and click &quot;+ Newsletter&quot; on an article.
          </p>
        )}

        {suggested.length > 0 && (
          <PoolGroup title="Suggested, not placed" count={suggested.length}>
            {suggested.map((entry) => (
              <PoolCard
                key={entry.article.id}
                entry={entry}
                state={state}
                paywall={paywallHints[entry.article.source]?.paywall_likely}
                onAssign={onAssign}
              />
            ))}
          </PoolGroup>
        )}

        {queue.length > 0 && (
          <PoolGroup
            title="Queued Articles"
            count={queue.length}
            action={
              <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={onClearAll}>
                Clear All
              </Button>
            }
          >
            {queue.map((a) => (
              <PoolCard
                key={a._id}
                entry={{ article: a as Article, origin: "queue" }}
                state={state}
                paywall={paywallHints[a.source]?.paywall_likely}
                onAssign={onAssign}
                onDiscard={() => onRemove(a._id)}
              />
            ))}
          </PoolGroup>
        )}
      </div>
    </div>
  );
}

function PoolGroup({ title, count, action, children }: { title: string; count: number; action?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <div className="mb-1.5 flex items-center justify-between">
        <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          {title} <span className="font-mono text-primary">{count}</span>
        </h3>
        {action}
      </div>
      <div className="space-y-1.5">{children}</div>
    </section>
  );
}

function PoolCard({
  entry,
  state,
  paywall,
  onAssign,
  onDiscard,
}: {
  entry: PoolEntry;
  state: ComposerState;
  paywall: boolean | undefined;
  onAssign: (slot: SlotKey, entry: PoolEntry) => void;
  /** Hanya antrean: membuang dari localStorage. Saran tidak punya "buang"; ia tetap tersedia. */
  onDiscard?: () => void;
}) {
  const a = entry.article;
  const countries = [...(a.victim_countries ?? []), ...(a.mentioned_countries ?? [])].slice(0, 3);
  const actors = (a.threat_actors ?? []).slice(0, 2);
  return (
    <div className="rounded-xl border border-border bg-background p-2.5">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-xs font-semibold text-foreground">{a.title}</div>
          <div className="mt-0.5 font-mono text-xs text-muted-foreground">
            {a.source} · {a.posted_on}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {a.news_type && (
              <Badge variant="outline" className="text-xs">
                {a.news_type}
              </Badge>
            )}
            {countries.map((c) => (
              <Badge key={c} variant="outline" className="text-xs">
                {c}
              </Badge>
            ))}
            {actors.map((t) => (
              <Badge key={t} variant="destructive" className="text-xs">
                {t}
              </Badge>
            ))}
            {paywall && (
              <Badge
                variant="outline"
                className="border-warning/40 bg-warning/10 text-xs text-warning"
                title="Paywall detected — summary will use metadata"
              >
                <TriangleAlertIcon aria-hidden /> Paywall
              </Badge>
            )}
          </div>
          {entry.reasons && (
            <div className="mt-1.5">
              <ReasonChips reasons={entry.reasons} />
            </div>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <DestinationMenu
            state={state}
            onPick={(slot) => onAssign(slot, entry)}
            triggerLabel="Add to the edition"
            trigger={<Button variant="outline" size="sm" className="h-6 w-6 p-0 text-sm leading-none" />}
          >
            +
          </DestinationMenu>
          {onDiscard && (
            <button
              type="button"
              onClick={onDiscard}
              title="Remove from queue"
              aria-label="Remove from queue"
              className="font-mono text-xs text-muted-foreground transition-colors hover:text-destructive"
            >
              <XIcon aria-hidden />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
