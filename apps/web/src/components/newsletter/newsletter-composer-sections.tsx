"use client";

import type { ReactNode } from "react";
import { ArrowDownIcon, ArrowRightLeftIcon, ArrowUpIcon, ReplaceIcon, XIcon } from "lucide-react";

import { DestinationMenu, ReasonChips } from "@/components/newsletter/article-parts";
import type { SECTION_BLOCKS } from "@/components/newsletter/types";
import { Chip } from "@/components/ui/chip";
import { Disclosure } from "@/components/ui/disclosure";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Switch } from "@/components/ui/switch";
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
import type { NewsletterSourceHint } from "@/lib/api/loose-types";
import type { components } from "@/lib/api/schema";
import { SLOT_BY_KEY, type ComposerState, type SectionName, type SlotKey } from "@/lib/newsletter/composer";

type Article = components["schemas"]["ArticleOut"];
type Reason = components["schemas"]["NewsletterSuggestionReason"];

/** Calon pengganti/tambahan di luar composer: saran yang belum ditempatkan atau antrean Newsroom. */
export interface PoolEntry {
  article: Article;
  origin: "suggestion" | "queue";
  reasons?: Reason[];
  /** Section dari saran (hanya entri saran); antrean menurunkannya dari negara artikel. */
  section?: SectionName;
}

export type TierView = "full" | "compact";

interface Props {
  /** Blok yang ditampilkan (Highlights atau satu section). */
  block: (typeof SECTION_BLOCKS)[number];
  view: TierView;
  onViewChange: (view: TierView) => void;
  state: ComposerState;
  pool: PoolEntry[];
  /** `body_sources` dari preview terakhir: `metadata` = ringkasan dari metadata saja. */
  bodySources: Record<string, string>;
  paywallHints: Record<string, NewsletterSourceHint>;
  /** Id yang akan dibangun ulang (fetch + LLM) pada preview berikutnya. */
  regenerate: ReadonlySet<number>;
  onMove: (articleId: number, to: SlotKey) => void;
  onRemove: (articleId: number) => void;
  onSwap: (outId: number, entry: PoolEntry) => void;
  onNoteChange: (articleId: number, value: string) => void;
  onToggleRegenerate: (articleId: number) => void;
}

const EMPTY = "No articles here yet. Place some from the queue.";

/**
 * Isi SATU blok bagian composer (Highlights atau satu section), dipilih di kolom Template. Tiap
 * section punya kartu penuh (ringkasan butuh fetch + LLM) dan daftar "Also Noted" (satu baris dari
 * metadata, tanpa fetch dan tanpa LLM); analis bisa menaikkan baris jadi kartu, menurunkan kartu
 * jadi baris, memindah, menukar dengan artikel lain, atau membuang. Batas jumlah ditegakkan
 * `lib/newsletter/composer`. Tidak ada seret-untuk-urut (spec D30).
 */
export function NewsletterComposerSections({ block, view, onViewChange, state, pool, bodySources, paywallHints, regenerate, ...handlers }: Props) {
  const fullDef = SLOT_BY_KEY[block.full];
  const compactDef = block.compact ? SLOT_BY_KEY[block.compact] : null;
  const cards = state.slots[block.full];
  const rows = block.compact ? state.slots[block.compact] : [];
  const showRows = compactDef !== null && view === "compact";

  return (
    <section aria-label={block.title}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div>
          <h2 className="font-heading text-lg leading-snug font-semibold text-foreground">{block.title}</h2>
          <p className="font-code text-xs text-muted-foreground">
            {compactDef ? `${cards.length} full cards · ${rows.length} compact` : `${cards.length} of ${fullDef.cap}`}
          </p>
        </div>
        {compactDef && (
          <SegmentedControl
            aria-label="Card style shown"
            value={view}
            onChange={onViewChange}
            options={[
              { value: "full", label: "Full" },
              { value: "compact", label: "Compact" },
            ]}
          />
        )}
      </div>

      {!showRows && (
        <div className="space-y-2">
          {cards.length === 0 && <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">{EMPTY}</p>}
          {cards.map((art) => (
            <ArticleCard
              key={art.id}
              article={art}
              slot={block.full}
              state={state}
              pool={pool}
              bodySource={bodySources[String(art.id)]}
              paywall={paywallHints[art.source]?.paywall_likely === true}
              regenerate={regenerate.has(art.id)}
              note={state.notes[String(art.id)] ?? ""}
              onMove={handlers.onMove}
              onRemove={handlers.onRemove}
              onSwap={handlers.onSwap}
              onNoteChange={handlers.onNoteChange}
              onToggleRegenerate={handlers.onToggleRegenerate}
            />
          ))}
          {compactDef && rows.length > 0 && (
            <button
              type="button"
              onClick={() => onViewChange("compact")}
              className="w-full rounded-lg bg-surface px-3 py-2 text-left text-2xs font-bold tracking-[0.1em] text-muted-foreground uppercase hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
            >
              Also noted · {rows.length} compact items
            </button>
          )}
        </div>
      )}

      {showRows && block.compact && (
        <>
          {rows.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">{EMPTY}</p>
          ) : (
            <ul className="space-y-1">
              {rows.map((art) => (
                <li key={art.id}>
                  <ArticleRow
                    article={art}
                    slot={block.compact!}
                    state={state}
                    pool={pool}
                    onMove={handlers.onMove}
                    onRemove={handlers.onRemove}
                    onSwap={handlers.onSwap}
                  />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
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
                    <span className="block font-code text-xs text-muted-foreground">
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
  paywall: boolean;
  regenerate: boolean;
  onNoteChange: (articleId: number, value: string) => void;
  onToggleRegenerate: (articleId: number) => void;
}

/** Kartu penuh (Highlights atau kartu section): judul, sumber, tanda periksa-ringkasan, alasan
 * saran, dan "Note and options" (catatan analis + bangun ulang ringkasan). Tombol aksi saudara
 * dari judul, bukan bersarang di dalam tombol lain. */
function ArticleCard({ article, note, bodySource, paywall, regenerate, onNoteChange, onToggleRegenerate, state, ...rest }: CardProps) {
  // Bukti dari preview ("halaman tidak terbaca") mengalahkan dugaan dari riwayat sumber.
  const flag =
    bodySource === "metadata"
      ? "CHECK SUMMARY · page could not be read"
      : paywall
        ? "CHECK SUMMARY · source is often paywalled"
        : null;
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-foreground">{article.title}</div>
          <div className="mt-0.5 font-code text-xs text-muted-foreground">
            {article.source} · {article.posted_on}
          </div>
        </div>
        <ItemActions article={article} state={state} {...rest} />
      </div>
      <div className="mt-2 space-y-2">
        {flag && <Chip kind="flag" value="check" className="bg-warning/15 text-warning-text">{flag}</Chip>}
        <ReasonChips reasons={state.reasons[article.id]} />
        <Disclosure title="Note and options" defaultOpen={note !== "" || regenerate}>
          <div className="space-y-2 pt-1">
            <Textarea
              aria-label={`Analyst note for ${article.title}`}
              placeholder="Analyst notes (optional)…"
              value={note}
              onChange={(e) => onNoteChange(article.id, e.target.value)}
              className="h-16 resize-y bg-panel text-xs"
            />
            <Switch
              checked={regenerate}
              onCheckedChange={() => onToggleRegenerate(article.id)}
              aria-label="Regenerate summary"
              label="Regenerate summary"
              className="text-xs"
            />
            <p className="text-xs text-muted-foreground">Fetches the page again and rewrites the summary on the next preview.</p>
          </div>
        </Disclosure>
      </div>
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
          <div className="font-code text-xs text-muted-foreground">
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
