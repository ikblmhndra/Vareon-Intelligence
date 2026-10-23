"use client";

import type { ReactNode } from "react";
import { ArrowDownIcon, ArrowRightLeftIcon, ArrowUpIcon, ReplaceIcon, TriangleAlertIcon, XIcon } from "lucide-react";

import { DestinationMenu, ReasonChips } from "@/components/newsletter/article-parts";
import { SectionIcon } from "@/components/newsletter/section-icon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Textarea } from "@/components/ui/textarea";
import type { components } from "@/lib/api/schema";
import { SECTIONS, SLOT_BY_KEY, type ComposerState, type SectionName, type SlotKey } from "@/lib/newsletter/composer";
import { cn } from "@/lib/utils";

type Article = components["schemas"]["ArticleOut"];
type Reason = components["schemas"]["NewsletterSuggestionReason"];

/** Calon pengganti/tambahan di luar composer: saran yang belum ditempatkan atau antrean Newsroom. */
export interface PoolEntry {
  article: Article;
  origin: "suggestion" | "queue";
  reasons?: Reason[];
}

interface Props {
  state: ComposerState;
  pool: PoolEntry[];
  /** `body_sources` dari preview terakhir: `metadata` = ringkasan dari metadata saja. */
  bodySources: Record<string, string>;
  /** Id yang akan dibangun ulang (fetch + LLM) pada preview berikutnya. */
  regenerate: ReadonlySet<number>;
  onMove: (articleId: number, to: SlotKey) => void;
  onRemove: (articleId: number) => void;
  onSwap: (outId: number, entry: PoolEntry) => void;
  onNoteChange: (articleId: number, value: string) => void;
  onToggleRegenerate: (articleId: number) => void;
}

const GROUPS: { key: "highlights" | SectionName; title: string; colorClass: string; full: SlotKey; compact: SlotKey | null }[] = [
  { key: "highlights", title: "Highlights", colorClass: "text-warning", full: "highlights", compact: null },
  ...SECTIONS.map((s) => ({
    key: s.key,
    title: s.label,
    colorClass: { apac: "text-primary", global_news: "text-tag-violet", indonesia: "text-destructive" }[s.key],
    full: `${s.key}_full` as SlotKey,
    compact: `${s.key}_compact` as SlotKey,
  })),
];

/**
 * Blok bagian composer: Highlights, Asia Pacific, Global, Indonesia. Tiap section punya kartu penuh
 * (key points + ringkasan, butuh fetch + LLM) dan daftar "Also Noted" (satu baris dari metadata,
 * tanpa fetch dan tanpa LLM); analis bisa menaikkan baris jadi kartu, menurunkan kartu jadi baris,
 * memindah, menukar dengan artikel lain, atau membuang. Batas jumlah ditegakkan `lib/newsletter/composer`.
 */
export function NewsletterComposerSections({
  state,
  pool,
  bodySources,
  regenerate,
  onMove,
  onRemove,
  onSwap,
  onNoteChange,
  onToggleRegenerate,
}: Props) {
  return (
    <div className="space-y-5">
      {GROUPS.map((g) => {
        const fullDef = SLOT_BY_KEY[g.full];
        const compactDef = g.compact ? SLOT_BY_KEY[g.compact] : null;
        const cards = state.slots[g.full];
        const rows = g.compact ? state.slots[g.compact] : [];
        return (
          <section key={g.key} aria-label={g.title}>
            <div
              className={cn(
                "mb-3 flex flex-wrap items-center justify-between gap-x-3 border-b border-border pb-2 text-sm font-semibold",
                g.colorClass,
              )}
            >
              <span className="flex items-center gap-2">
                <SectionIcon section={g.key} /> {g.title}
              </span>
              <span className="font-mono text-xs font-normal text-muted-foreground">
                {cards.length} / {fullDef.cap} {g.key === "highlights" ? "" : "cards"}
                {compactDef && ` · ${rows.length} / ${compactDef.cap} Also Noted`}
              </span>
            </div>

            <div className="space-y-1.5">
              {cards.length === 0 && (
                <div className="flex min-h-12 items-center justify-center rounded-xl border border-dashed border-border bg-background px-3 py-3 text-center">
                  <span className="text-sm text-muted-foreground">
                    No {g.key === "highlights" ? "highlights" : "cards"} yet — add from the suggested or queued articles (max {fullDef.cap})
                  </span>
                </div>
              )}
              {cards.map((art) => (
                <ArticleCard
                  key={art.id}
                  article={art}
                  slot={g.full}
                  state={state}
                  pool={pool}
                  bodySource={bodySources[String(art.id)]}
                  regenerate={regenerate.has(art.id)}
                  note={state.notes[String(art.id)] ?? ""}
                  onMove={onMove}
                  onRemove={onRemove}
                  onSwap={onSwap}
                  onNoteChange={onNoteChange}
                  onToggleRegenerate={onToggleRegenerate}
                />
              ))}
            </div>

            {compactDef && g.compact && (
              <div className="mt-3">
                <div className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Also Noted</div>
                {rows.length === 0 ? (
                  <p className="rounded-xl border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                    No rows. These are one-line entries (title, source, date) that cost no page fetch and no model call.
                  </p>
                ) : (
                  <ul className="space-y-1">
                    {rows.map((art) => (
                      <li key={art.id}>
                        <ArticleRow
                          article={art}
                          slot={g.compact!}
                          state={state}
                          pool={pool}
                          onMove={onMove}
                          onRemove={onRemove}
                          onSwap={onSwap}
                        />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}

// ── Satu artikel ────────────────────────────────────────────────────────────

interface ItemProps {
  article: Article;
  slot: SlotKey;
  state: ComposerState;
  pool: PoolEntry[];
  onMove: (articleId: number, to: SlotKey) => void;
  onRemove: (articleId: number) => void;
  onSwap: (outId: number, entry: PoolEntry) => void;
}

/** Tombol ikon kecil seragam untuk aksi per artikel. */
function ActionButton({ title, onClick, className, children }: { title: string; onClick?: () => void; className?: string; children: ReactNode }) {
  return (
    <Button type="button" variant="ghost" size="icon-xs" title={title} aria-label={title} onClick={onClick} className={className}>
      {children}
    </Button>
  );
}

/** Naik/turun satu tier di section yang sama. Tetap bisa diklik saat batas penuh: `onMove`
 * menjawab dengan pesan yang menyebut batasnya (lebih jelas dari tombol mati tanpa alasan). */
function TierButton({ article, slot, onMove }: Pick<ItemProps, "article" | "slot" | "onMove">) {
  const { tier, section } = SLOT_BY_KEY[slot];
  if (tier === "highlight" || section === null) return null;
  return tier === "compact" ? (
    <ActionButton title="Make full card" onClick={() => onMove(article.id, `${section}_full`)}>
      <ArrowUpIcon aria-hidden />
    </ActionButton>
  ) : (
    <ActionButton title="Move to Also Noted" onClick={() => onMove(article.id, `${section}_compact`)}>
      <ArrowDownIcon aria-hidden />
    </ActionButton>
  );
}

function ItemActions({ article, slot, state, pool, onMove, onRemove, onSwap }: ItemProps) {
  return (
    <div className="flex shrink-0 items-center gap-0.5">
      <TierButton article={article} slot={slot} onMove={onMove} />
      <DestinationMenu
        state={state}
        current={slot}
        onPick={(to) => onMove(article.id, to)}
        triggerLabel="Move to another section or tier"
        trigger={<Button type="button" variant="ghost" size="icon-xs" />}
      >
        <ArrowRightLeftIcon aria-hidden />
      </DestinationMenu>
      <SwapMenu outId={article.id} pool={pool} onSwap={onSwap} />
      <ActionButton title="Remove from the edition" onClick={() => onRemove(article.id)} className="hover:text-destructive">
        <XIcon aria-hidden />
      </ActionButton>
    </div>
  );
}

/** Tukar dengan artikel lain dari saran yang belum ditempatkan atau dari antrean Newsroom; yang
 * ditukar jadi kembali ke kolam. Posisi dan tier-nya dipakai artikel baru. */
function SwapMenu({ outId, pool, onSwap }: { outId: number; pool: PoolEntry[]; onSwap: (outId: number, entry: PoolEntry) => void }) {
  const groups: { label: string; origin: PoolEntry["origin"] }[] = [
    { label: "Suggested, not placed", origin: "suggestion" },
    { label: "Your queue", origin: "queue" },
  ];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button type="button" variant="ghost" size="icon-xs" />}
        aria-label="Swap with another article"
        title="Swap with another article"
      >
        <ReplaceIcon aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-72 w-80 max-w-[90vw]">
        {pool.length === 0 && (
          <DropdownMenuItem disabled>No other articles. Queue some from the Newsroom with “+ Newsletter”.</DropdownMenuItem>
        )}
        {groups.map(({ label, origin }) => {
          const entries = pool.filter((p) => p.origin === origin);
          if (entries.length === 0) return null;
          return (
            <DropdownMenuGroup key={origin}>
              <DropdownMenuLabel>{label}</DropdownMenuLabel>
              {entries.map((p) => (
                <DropdownMenuItem key={p.article.id} onClick={() => onSwap(outId, p)} className="items-start">
                  <span className="min-w-0 flex-1">
                    <span className="line-clamp-2 text-xs font-medium">{p.article.title}</span>
                    <span className="block font-mono text-xs text-muted-foreground">
                      {p.article.source} · {p.article.posted_on}
                    </span>
                  </span>
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

interface CardProps extends ItemProps {
  note: string;
  bodySource: string | undefined;
  regenerate: boolean;
  onNoteChange: (articleId: number, value: string) => void;
  onToggleRegenerate: (articleId: number) => void;
}

/** Kartu penuh (Highlights atau kartu section): judul, sumber, alasan saran, tanda ringkasan dari
 * metadata, dan catatan analis. */
function ArticleCard({ article, note, bodySource, regenerate, onNoteChange, onToggleRegenerate, state, ...rest }: CardProps) {
  const metadataOnly = bodySource === "metadata";
  return (
    <div className="rounded-xl border border-border bg-background p-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-xs font-semibold text-foreground">{article.title}</div>
          <div className="mt-0.5 font-mono text-xs text-muted-foreground">
            {article.source} · {article.posted_on}
          </div>
        </div>
        <ItemActions article={article} state={state} {...rest} />
      </div>
      <div className="mt-1.5 space-y-1.5">
        <ReasonChips reasons={state.reasons[article.id]} />
        {metadataOnly && (
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              variant="outline"
              className="border-warning/40 bg-warning/10 text-xs text-warning-text"
              title="The page could not be read (paywall or fetch failure), so the summary was written from the title and metadata only. Check it before sending."
            >
              <TriangleAlertIcon aria-hidden /> Summary from metadata only
            </Badge>
            <Button
              type="button"
              variant="ghost"
              size="xs"
              aria-pressed={regenerate}
              onClick={() => onToggleRegenerate(article.id)}
              title="Fetch the page again and rewrite the summary on the next preview"
            >
              {regenerate ? "Will re-summarise on next preview" : "Re-summarise"}
            </Button>
          </div>
        )}
      </div>
      <Textarea
        placeholder="Analyst notes (optional)…"
        value={note}
        onChange={(e) => onNoteChange(article.id, e.target.value)}
        className="mt-2 h-14 resize-y bg-panel font-mono text-xs"
      />
    </div>
  );
}

/** Baris "Also Noted": satu baris dari metadata tersimpan, tanpa catatan dan tanpa ringkasan. */
function ArticleRow({ article, state, ...rest }: ItemProps) {
  return (
    <div className="rounded-lg border border-border bg-background px-2.5 py-1.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-xs font-medium text-foreground" title={article.title}>
            {article.title}
          </div>
          <div className="font-mono text-xs text-muted-foreground">
            {article.source} · {article.posted_on}
            {article.news_type ? ` · ${article.news_type}` : ""}
          </div>
        </div>
        <ItemActions article={article} state={state} {...rest} />
      </div>
      {state.reasons[article.id] && (
        <div className="mt-1">
          <ReasonChips reasons={state.reasons[article.id]} />
        </div>
      )}
    </div>
  );
}
