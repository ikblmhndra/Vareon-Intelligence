"use client";

import { useState, type ComponentProps } from "react";

import {
  NewsletterComposerSections,
  type TierView,
} from "@/components/newsletter/newsletter-composer-sections";
import { NewsletterSummaryField } from "@/components/newsletter/newsletter-summary-field";
import { NewsletterTemplatePanel } from "@/components/newsletter/newsletter-template-panel";
import { SECTION_BLOCKS, type BlockId, type TemplateState } from "@/components/newsletter/types";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type SectionsProps = Omit<ComponentProps<typeof NewsletterComposerSections>, "block" | "view" | "onViewChange">;

interface Props {
  block: BlockId;
  sections: SectionsProps;
  summary: ComponentProps<typeof NewsletterSummaryField>;
  template: TemplateState;
  onTemplateChange: (value: TemplateState) => void;
}

/** Kolom isi: menampilkan SATU blok yang dipilih di kolom Template. Pilihan Full/Compact hidup di
 * sini dan kembali ke Full tiap pindah blok (pola "sesuaikan state saat render"). */
export function NewsletterContentColumn({ block, sections, summary, template, onTemplateChange }: Props) {
  const [view, setView] = useState<TierView>("full");
  const [prevBlock, setPrevBlock] = useState(block);
  if (prevBlock !== block) {
    setPrevBlock(block);
    setView("full");
  }

  const sectionBlock = SECTION_BLOCKS.find((b) => b.id === block);

  return (
    <Card className="min-w-0">
      {sectionBlock ? (
        <CardContent>
          <NewsletterComposerSections {...sections} block={sectionBlock} view={view} onViewChange={setView} />
        </CardContent>
      ) : block === "summary" ? (
        <CardContent>
          <NewsletterSummaryField {...summary} />
        </CardContent>
      ) : (
        <>
          <CardHeader>
            <CardTitle>{block === "clusters" ? "Campaign clusters" : "Footer and CSS"}</CardTitle>
            <CardDescription>
              {block === "clusters" ? "An extra section listing the top campaigns of the lookback window" : "Custom styling and footer for the whole email"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <NewsletterTemplatePanel value={template} onChange={onTemplateChange} part={block === "clusters" ? "clusters" : "footer"} />
          </CardContent>
        </>
      )}
    </Card>
  );
}
