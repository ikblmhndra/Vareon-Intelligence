"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PirArticlesDialog } from "@/components/intelligence/pir/pir-articles-dialog";
import type { MatchedPir } from "@/lib/api/loose-types";
import type { components } from "@/lib/api/schema";

type PIROut = components["schemas"]["PIROut"];

function Chips({ items }: { items: string[] | undefined }) {
  if (!items || items.length === 0) return <span className="font-mono text-xs text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((v, i) => (
        <span key={i} className="rounded-full border border-primary/25 bg-primary/8 px-1.5 py-0.5 font-mono text-xs text-primary-text">
          {v}
        </span>
      ))}
    </div>
  );
}

const PRIORITY_COLOR: Record<string, string> = { P1: "text-destructive", P2: "text-warning" };

/** Port `_showClusterPirModal()`/`openClusterPir()` (`clusters.js:641-716`)
 * -- detail PIR yang match campaign, "View Matching Articles" numpang
 * `PirArticlesDialog` (Grup G2) lewat objek minimal `{id,title}`. */
export function ClusterPirDialog({ pir, onClose }: { pir: MatchedPir | null; onClose: () => void }) {
  const [viewingArticles, setViewingArticles] = useState(false);

  return (
    <>
      <Dialog open={pir !== null && !viewingArticles} onOpenChange={(open) => !open && onClose()}>
        <DialogContent className="sm:max-w-lg">
          {pir && (
            <>
              <DialogHeader>
                <div className="flex items-center gap-2">
                  <Badge variant="destructive" className="text-xs">
                    PIR
                  </Badge>
                  <span className={`font-mono text-xs font-bold ${PRIORITY_COLOR[pir.priority] ?? "text-muted-foreground"}`}>{pir.priority}</span>
                  <span className="font-mono text-xs text-muted-foreground">{pir.status}</span>
                </div>
                <DialogTitle className="text-base">{pir.title}</DialogTitle>
              </DialogHeader>

              {pir.description && <p className="rounded-xl border border-border bg-background p-2.5 text-xs leading-relaxed text-foreground">{pir.description}</p>}

              <div className="grid gap-2.5">
                {(pir.criteria.threat_actors?.length ?? 0) > 0 && (
                  <div>
                    <div className="mb-1 text-sm font-semibold text-muted-foreground">Threat Actors</div>
                    <Chips items={pir.criteria.threat_actors} />
                  </div>
                )}
                {(pir.criteria.industries?.length ?? 0) > 0 && (
                  <div>
                    <div className="mb-1 text-sm font-semibold text-muted-foreground">Industries</div>
                    <Chips items={pir.criteria.industries} />
                  </div>
                )}
                {(pir.criteria.countries?.length ?? 0) > 0 && (
                  <div>
                    <div className="mb-1 text-sm font-semibold text-muted-foreground">Countries</div>
                    <Chips items={pir.criteria.countries} />
                  </div>
                )}
                {(pir.criteria.keywords?.length ?? 0) > 0 && (
                  <div>
                    <div className="mb-1 text-sm font-semibold text-muted-foreground">Keywords</div>
                    <Chips items={pir.criteria.keywords} />
                  </div>
                )}
                {(pir.criteria.ttps?.length ?? 0) > 0 && (
                  <div>
                    <div className="mb-1 text-sm font-semibold text-muted-foreground">TTPs</div>
                    <Chips items={pir.criteria.ttps} />
                  </div>
                )}
              </div>

              <div className="flex justify-end">
                <Button size="sm" variant="outline" onClick={() => setViewingArticles(true)}>
                  View Matching Articles →
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      <PirArticlesDialog
        pir={viewingArticles && pir ? ({ id: pir.id, title: pir.title } as PIROut) : null}
        onClose={() => {
          setViewingArticles(false);
          onClose();
        }}
      />
    </>
  );
}
