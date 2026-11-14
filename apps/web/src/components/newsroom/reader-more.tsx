"use client";

import { useState } from "react";

import { HuntPanel } from "@/components/hunt/hunt-panel";
import { D3fendToggle } from "@/components/newsroom/d3fend-toggle";
import { InferredTtpsSection } from "@/components/newsroom/inferred-ttps-section";
import { Disclosure } from "@/components/ui/disclosure";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";

type Article = components["schemas"]["ArticleOut"];

/**
 * Bagian "More" pembaca (spec 6.4 blok 9). Isinya baru dipasang sesudah pertama kali dibuka, supaya
 * request hunt pack, D3FEND, dan TTP turunan tidak jalan untuk artikel yang tidak diperluas.
 */
export function ReaderMore({ article }: { article: Article }) {
  const [opened, setOpened] = useState(false);
  const can = useCan();
  // Tiap blok hanya dipasang bila perannya boleh membuat request-nya: hunt pack butuh `view_ioc`,
  // D3FEND (/api/mitre/*) butuh `view_intel` (spec 8: tidak ada request tanpa izin).
  const showHunt = can("view_ioc") && article.story != null;
  const showD3fend = can("view_intel") && article.ttps.length > 0;
  return (
    <Disclosure title="More" headingLevel={3} onOpenChange={(o) => o && setOpened(true)}>
      {opened && (
        <div className="space-y-4 pt-2">
          {article.classify_inherited_from != null && (
            <p className="text-xs text-muted-foreground">Classification inherited from the lead article.</p>
          )}
          {showHunt && article.story && <HuntPanel key={article.story.id} anchorType="story" anchorId={article.story.id} />}
          {showD3fend && (
            <div className="space-y-1.5">
              <h4 className="text-xs font-semibold text-muted-foreground">Defenses (D3FEND)</h4>
              <ul className="space-y-1.5">
                {article.ttps.map((t) => (
                  <li key={t.id} className="flex items-center gap-2 text-xs">
                    <span className="font-code text-foreground">{t.id}</span>
                    <span className="min-w-0 flex-1 text-muted-foreground">{t.name}</span>
                    <D3fendToggle ttpId={t.id} />
                  </li>
                ))}
              </ul>
            </div>
          )}
          <InferredTtpsSection articleId={article.id} />
        </div>
      )}
    </Disclosure>
  );
}
