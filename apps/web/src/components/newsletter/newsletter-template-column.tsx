"use client";

import type { ReactNode } from "react";

import { SectionIcon } from "@/components/newsletter/section-icon";
import { SECTION_BLOCKS, type BlockId, type SummaryLanguage, type TemplateState } from "@/components/newsletter/types";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Disclosure } from "@/components/ui/disclosure";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SelectableList } from "@/components/ui/selectable-list";
import { SLOT_BY_KEY, type ComposerState } from "@/lib/newsletter/composer";
import { daysIn, type MonthOption } from "@/lib/newsletter/period";

const LANGUAGE_ITEMS: Record<SummaryLanguage, string> = { id: "Indonesian", en: "English" };

interface Props {
  months: readonly MonthOption[];
  period: string;
  onPeriodChange: (value: string) => void;
  language: SummaryLanguage;
  onLanguageChange: (value: SummaryLanguage) => void;
  /** Jumlah kartu penuh yang sudah ditempatkan; dasar penjelasan biaya ringkasan. */
  cardCount: number;
  state: ComposerState;
  template: TemplateState;
  block: BlockId;
  onBlockChange: (block: BlockId) => void;
}

function summaryCost(language: SummaryLanguage, cardCount: number): string {
  return language === "id"
    ? `The first Indonesian build summarises every full card again (one page fetch and one model call each; ${cardCount} ${cardCount === 1 ? "card" : "cards"} now). Later builds reuse the stored summaries. Also Noted rows cost nothing.`
    : "English summaries are stored separately from Indonesian ones, so switching back loses nothing. The first English build summarises each full card (one page fetch and one model call).";
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor} className="text-2xs font-bold tracking-[0.1em] text-muted-foreground uppercase">
        {label}
      </Label>
      {children}
    </div>
  );
}

/**
 * Kolom kiri komposer: periode, bahasa ringkasan, dan daftar blok yang dipilih untuk disunting di
 * kolom isi. Daftar dipecah dua (blok artikel, lalu "Also in the email") karena `SelectableList`
 * tidak punya pemisah; tiap daftar tetap bisa dioperasikan dengan panah dan Tab pindah antar daftar.
 */
export function NewsletterTemplateColumn({
  months,
  period,
  onPeriodChange,
  language,
  onLanguageChange,
  cardCount,
  state,
  template,
  block,
  onBlockChange,
}: Props) {
  const periodItems = Object.fromEntries(months.map((m) => [m.value, m.label]));
  const selected = months.find((m) => m.value === period);

  const sectionItems = SECTION_BLOCKS.map((b) => {
    const full = state.slots[b.full].length;
    const compact = b.compact ? state.slots[b.compact].length : 0;
    const sub = b.compact ? `${full} full · ${compact} compact` : `${full} of ${SLOT_BY_KEY[b.full].cap}`;
    return { value: b.id as BlockId, title: b.title, sub, icon: b.id };
  });
  const introLength = template.customIntro.trim().length;
  const emailItems: { value: BlockId; title: string; sub: string }[] = [
    { value: "summary", title: "Executive summary", sub: introLength > 0 ? `${introLength} characters` : "empty" },
    { value: "clusters", title: "Campaign clusters", sub: template.includeClusters ? `Last ${template.clusterDays} days` : "Off" },
    {
      value: "footer",
      title: "Footer and CSS",
      sub: template.customCss.trim() || template.customFooter.trim() ? "Customised" : "Default",
    },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Template</CardTitle>
        <CardDescription>Period and sections</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <Field label="Period" htmlFor="newsletter-period">
          <Select items={periodItems} value={period} onValueChange={(v) => v && onPeriodChange(v)}>
            <SelectTrigger id="newsletter-period" aria-label="Period" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {months.map((m) => (
                <SelectItem key={m.value} value={m.value}>
                  {m.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {selected && <p className="font-code text-xs text-muted-foreground">{daysIn(selected.start, selected.end)} days</p>}
        </Field>

        <Field label="Language" htmlFor="newsletter-language">
          <Select items={LANGUAGE_ITEMS} value={language} onValueChange={(v) => v && onLanguageChange(v as SummaryLanguage)}>
            <SelectTrigger id="newsletter-language" aria-label="Summary language" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(LANGUAGE_ITEMS).map(([val, label]) => (
                <SelectItem key={val} value={val}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Disclosure title="About summaries">
            <p className="text-xs text-muted-foreground">{summaryCost(language, cardCount)}</p>
          </Disclosure>
        </Field>

        <SelectableList
          aria-label="Content blocks"
          items={sectionItems}
          value={block}
          onChange={onBlockChange}
          renderItem={(item) => (
            <span className="flex items-start gap-2">
              <SectionIcon section={item.icon} className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0">
                <span className="block text-sm font-medium text-foreground">{item.title}</span>
                <span className="block font-code text-xs text-muted-foreground">{item.sub}</span>
              </span>
            </span>
          )}
        />

        <div className="space-y-1.5 border-t border-border pt-4">
          <p aria-hidden className="px-3 text-2xs font-bold tracking-[0.1em] text-muted-foreground uppercase">
            Also in the email
          </p>
          <SelectableList
            aria-label="Also in the email"
            items={emailItems}
            value={block}
            onChange={onBlockChange}
            renderItem={(item) => (
              <span className="block">
                <span className="block text-sm font-medium text-foreground">{item.title}</span>
                <span className="block font-code text-xs text-muted-foreground">{item.sub}</span>
              </span>
            )}
          />
        </div>
      </CardContent>
    </Card>
  );
}
