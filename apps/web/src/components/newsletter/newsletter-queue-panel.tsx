"use client";

import type { ReactNode } from "react";
import { XIcon } from "lucide-react";

import { DestinationMenu } from "@/components/newsletter/article-parts";
import type { PoolEntry } from "@/components/newsletter/newsletter-composer-sections";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EntityChip } from "@/components/entities/entity-chip";
import { Chip } from "@/components/ui/chip";
import { actorChips, countryChip } from "@/lib/entities/article-refs";
import type { NewsletterSourceHint } from "@/lib/api/loose-types";
import type { components } from "@/lib/api/schema";
import type { ComposerState, SectionName, SlotKey } from "@/lib/newsletter/composer";
import type { QueueArticle } from "@/lib/newsletter/queue";
import { cn } from "@/lib/utils";

type Article = components["schemas"]["ArticleOut"];

const SECTION_LABEL: Record<SectionName, string> = { apac: "Asia Pacific", global_news: "Global", indonesia: "Indonesia" };

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
 * dengan alasannya) dan "Queued articles" (tombol "+ Newsletter" di Newsroom, lewat localStorage
 * key `newsletter_queue`, lihat `lib/newsletter/queue.ts`, kontraknya tidak berubah). Tautan
 * "+ Add articles" membuka Newsroom di tab baru (spec D31); `storage` listener di view
 * menyegarkan antrean saat artikel masuk dari tab itu. */
export function NewsletterQueuePanel({ state, queue, suggested, paywallHints, onAssign, onRemove, onClearAll }: Props) {
  const total = suggested.length + queue.length;
  const addLink = (
    <div className="space-y-1">
      <a href="/newsroom" target="_blank" rel="noopener" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-full")}>
        + Add articles
      </a>
      <p className="text-center text-2xs text-muted-foreground">Use + Newsletter on any article</p>
    </div>
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your queue</CardTitle>
        <CardDescription>
          {total} {total === 1 ? "article" : "articles"} · {suggested.length} suggested, not placed
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {total === 0 && (
          <div className="space-y-3 py-4 text-center">
            <p className="text-sm font-semibold text-foreground">Your queue is empty</p>
          </div>
        )}

        {suggested.length > 0 && (
          <PoolGroup title="Suggested, not placed" count={suggested.length}>
            {suggested.map((entry) => (
              <PoolRow
                key={entry.article.id}
                entry={entry}
                section={entry.section ? SECTION_LABEL[entry.section] : null}
                state={state}
                paywall={paywallHints[entry.article.source]?.paywall_likely}
                onAssign={onAssign}
              />
            ))}
          </PoolGroup>
        )}

        {queue.length > 0 && (
          <PoolGroup
            title="Queued articles"
            count={queue.length}
            action={
              <Button variant="ghost" size="xs" onClick={onClearAll}>
                Clear all
              </Button>
            }
          >
            {queue.map((a) => (
              <PoolRow
                key={a._id}
                entry={{ article: a as Article, origin: "queue" }}
                // Sama dengan aturan server: Indonesia bila ID ada di negara korban atau yang disebut.
                section={[...(a.victim_countries ?? []), ...(a.mentioned_countries ?? [])].includes("ID") ? SECTION_LABEL.indonesia : null}
                state={state}
                paywall={paywallHints[a.source]?.paywall_likely}
                onAssign={onAssign}
                onDiscard={() => onRemove(a._id)}
              />
            ))}
          </PoolGroup>
        )}

        {addLink}
      </CardContent>
    </Card>
  );
}

function PoolGroup({ title, count, action, children }: { title: string; count: number; action?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <div className="mb-1.5 flex items-center justify-between">
        <h3 className="text-2xs font-bold tracking-[0.1em] text-muted-foreground uppercase">
          {title} <span className="font-code text-foreground">{count}</span>
        </h3>
        {action}
      </div>
      <div className="space-y-1.5">{children}</div>
    </section>
  );
}

function PoolRow({
  entry,
  section,
  state,
  paywall,
  onAssign,
  onDiscard,
}: {
  entry: PoolEntry;
  section: string | null;
  state: ComposerState;
  paywall: boolean | undefined;
  onAssign: (slot: SlotKey, entry: PoolEntry) => void;
  /** Hanya antrean: membuang dari localStorage. Saran tidak punya "buang"; ia tetap tersedia. */
  onDiscard?: () => void;
}) {
  const a = entry.article;
  // Negara bisa ada di victim DAN mentioned: satu chip saja (key kembar). Chip aktor/negara tetap
  // terjangkau dari antrean (fitur lama), di baris sendiri supaya tidak bersarang di kontrol lain.
  const countries = [...new Set([...(a.victim_countries ?? []), ...(a.mentioned_countries ?? [])])].slice(0, 3);
  const actors = actorChips(a).slice(0, 2);
  return (
    <div className="rounded-lg border border-border bg-background p-2.5">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-xs font-semibold text-foreground">{a.title}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
            {section && <Chip kind="flag" value={section} />}
            <span className="font-code text-2xs text-muted-foreground">
              {a.source} · {a.posted_on}
            </span>
          </div>
          {(countries.length > 0 || actors.length > 0) && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {countries.map((c) => (
                <EntityChip key={c} {...countryChip(a, c)} />
              ))}
              {actors.map((t) => (
                <EntityChip key={t.name} {...t} />
              ))}
            </div>
          )}
          {entry.reasons && entry.reasons.length > 0 && (
            <p className="mt-1.5 text-2xs text-muted-foreground">
              <span className="font-semibold">Why suggested:</span> {entry.reasons.map((r) => r.text).join(" · ")}
            </p>
          )}
          {paywall && <p className="mt-1 text-2xs text-warning-text">Paywall likely: the summary will use metadata only.</p>}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <DestinationMenu
            state={state}
            onPick={(slot) => onAssign(slot, entry)}
            triggerLabel="Add to the edition"
            trigger={<Button variant="outline" size="icon-xs" />}
          >
            +
          </DestinationMenu>
          {onDiscard && (
            <Button variant="ghost" size="icon-xs" title="Remove from queue" aria-label="Remove from queue" onClick={onDiscard} className="hover:text-destructive">
              <XIcon aria-hidden />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
