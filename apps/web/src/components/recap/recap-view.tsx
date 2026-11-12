import type { ReactNode } from "react";

import type { RecapDoc, RecapHitRate, RecapVerdict } from "@/lib/api/loose-types";
import { isoWeek } from "@/lib/recap/period";
import { dropReason, effectiveVerdict, safeHttpUrl } from "@/lib/recap/quality";
import { fmtDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Disclosure } from "@/components/ui/disclosure";
import { Notice } from "@/components/ui/notice";
import { ConfidenceBadge, Chips, EmptyNote } from "@/components/recap/recap-parts";
import { ComparisonBlock, HitRateBlock, ScorecardBlock } from "@/components/recap/recap-quality";
import { RecapTiles } from "@/components/recap/recap-tiles";

const VERDICT_WORD: Record<RecapVerdict, string> = {
  happened: "hit",
  partly: "partly",
  not_happened: "miss",
  unclear: "unclear",
};

function SideCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

/** Peringatan grounding: yang dibuang cek grounding tidak hilang diam-diam, rinciannya di `<details>`. */
function GroundingNotice({ doc }: { doc: RecapDoc }) {
  const grounding = doc.quality?.grounding;
  const dropped = grounding?.dropped ?? [];
  const count = grounding?.count || dropped.length;
  if (!count) return null;
  return (
    <Notice tone="warning" title={`Grounding check: ${count} ${count === 1 ? "item" : "items"} dropped`}>
      <details>
        <summary className="cursor-pointer text-xs font-medium text-foreground">Show details</summary>
        <p className="mt-2">
          The model wrote these, but they are not in the data it was given, so they were removed from
          this recap instead of being shown.
        </p>
        <ul className="mt-2 space-y-1.5">
          {dropped.map((d, i) => (
            <li
              key={i}
              className="grid grid-cols-1 gap-x-3 gap-y-0.5 border-t border-border/60 pt-1.5 text-sm first:border-t-0 first:pt-0 sm:grid-cols-[10rem_1fr]"
            >
              <span className="font-code text-xs text-muted-foreground">{d.field}</span>
              <span className="min-w-0">
                <span className="break-words text-foreground">{d.value || "(empty)"}</span>
                <span className="ml-2 text-xs text-muted-foreground">· {dropReason(d.reason)}</span>
              </span>
            </li>
          ))}
        </ul>
      </details>
    </Notice>
  );
}

/**
 * Satu dokumen recap (harian atau mingguan). Isi mingguan juga ada di `doc.yesterday` (nama kolom
 * lama). Blok kualitas (`doc.quality`, `hitRate`) dipasang hanya kalau datanya ada, jadi recap lama
 * dan recap harian tetap tampil utuh. Tidak ada elemen interaktif di dalam baris cerita: tautan
 * sumber adalah saudara judul, bukan pembungkusnya.
 */
export function RecapView({ doc, hitRate }: { doc: RecapDoc; hitRate?: RecapHitRate }) {
  const recap = doc.yesterday || {};
  const fcast = doc.forecast || {};
  const weekly = doc.kind === "weekly";
  const quality = doc.quality ?? {};
  const stories = recap.top_stories ?? [];
  const events = fcast.likely_events ?? [];
  const tokens = doc.token_usage?.total_tokens;
  const isEmpty = !doc.headline && !recap.summary;
  // Pekan depan = ISO week dari Senin + 7 hari (bukan nomor + 1: pekan 53 diikuti pekan 1).
  const nextWeek = weekly
    ? isoWeek(new Date(Date.parse(doc.period_start) + 7 * 86_400_000).toISOString().slice(0, 10))
    : null;
  const scorecard = quality.scorecard;
  // "Each links to its source article" hanya benar bila SEMUA cerita punya url (recap lama tidak).
  const allLinked = stories.length > 0 && stories.every((s) => !!safeHttpUrl(s.url));
  const groundingClean = !quality.grounding || !(quality.grounding.count || quality.grounding.dropped?.length);

  return (
    <div className="space-y-4">
      {isEmpty ? (
        <Notice tone="warning" title="This recap is empty">
          The model reply {doc.raw_llm ? "could not be read (raw text below)" : "had no content"}. Generate it
          again from Regenerate.
          {doc.raw_llm && (
            <Disclosure title="Raw LLM output (parse fallback)" className="mt-2">
              <pre className="mt-1.5 rounded-md border border-border p-2.5 text-xs whitespace-pre-wrap text-muted-foreground">
                {doc.raw_llm}
              </pre>
            </Disclosure>
          )}
        </Notice>
      ) : (
        <GroundingNotice doc={doc} />
      )}

      <RecapTiles doc={doc} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_432px]">
        <div className="min-w-0 space-y-4">
          <Card>
            <CardHeader>
              <CardDescription className="text-2xs font-semibold tracking-wide uppercase">
                Summary
              </CardDescription>
              <CardTitle className="text-xl">{doc.headline || "(no headline)"}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm leading-relaxed">{recap.summary || "(no summary)"}</p>
              <p className="text-2xs text-muted-foreground">
                {doc.token_usage?.skipped
                  ? "LLM skipped (no activity)"
                  : `Generated ${fmtDateTime(doc.generated_at)} · ${doc.model}${tokens ? ` · ${tokens} tokens` : ""}`}
                {!isEmpty && groundingClean && " · Grounding check: nothing was dropped"}
                {weekly && " · Weeks run Monday-Sunday by UTC date."}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Top stories</CardTitle>
              <CardDescription>
                {allLinked
                  ? "Each links to its source article"
                  : "Links appear for stories matched to an article."}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {stories.length ? (
                <ol className="divide-y divide-border">
                  {stories.map((s, i) => {
                    const href = safeHttpUrl(s.url);
                    return (
                      <li key={i} className="flex gap-3 py-3 first:pt-0 last:pb-0">
                        <span className="font-code text-xs text-muted-foreground">
                          {String(i + 1).padStart(2, "0")}
                        </span>
                        <div className="min-w-0 space-y-1">
                          <p className="text-sm font-semibold">{s.title}</p>
                          {s.why_it_matters && (
                            <p className="text-sm text-muted-foreground">{s.why_it_matters}</p>
                          )}
                          {href ? (
                            <a
                              href={href}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs font-medium text-primary-text underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                            >
                              {s.source || "Source"} ↗
                            </a>
                          ) : (
                            <p className="text-xs text-muted-foreground">{s.source || "?"}</p>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ol>
              ) : (
                <EmptyNote />
              )}
            </CardContent>
          </Card>
        </div>

        <div className="min-w-0 space-y-4">
          <SideCard title="Active threat actors">
            <Chips items={recap.active_threat_actors} entity="intrusion-set" />
          </SideCard>
          <SideCard title="Notable CVEs">
            <Chips items={recap.notable_cves} entity="vulnerability" />
          </SideCard>
          {(recap.apac_signals ?? []).length > 0 && (
            <SideCard title="APAC signals">
              <ul className="list-disc space-y-1 pl-4 text-sm leading-snug">
                {recap.apac_signals!.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </SideCard>
          )}
        </div>
      </div>

      <div className={cn("grid grid-cols-1 gap-4", weekly && "lg:grid-cols-2")}>
        <Card>
          <CardHeader>
            <CardTitle>{weekly ? `Forecast for week ${nextWeek}` : "Forecast for the next 1-3 days"}</CardTitle>
            <CardDescription>
              {weekly ? "Each forecast is scored next week" : "Daily forecasts are not scored."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm leading-relaxed text-muted-foreground">
              {fcast.summary || "(no forecast)"}
            </p>
            {events.length ? (
              <ul className="divide-y divide-border">
                {events.map((e, i) => (
                  <li key={i} className="space-y-1 py-2.5 first:pt-0 last:pb-0">
                    <div className="flex items-start gap-2">
                      {e.id && <span className="font-code text-xs text-muted-foreground">{e.id}</span>}
                      <span className="min-w-0 flex-1 text-sm font-medium">{e.event}</span>
                      <ConfidenceBadge confidence={e.confidence} />
                    </div>
                    <p className="text-xs text-muted-foreground">Basis: {e.basis}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyNote />
            )}
            {(fcast.watch_items ?? []).length > 0 && (
              <div>
                <h3 className="mb-1.5 text-sm font-semibold">Watch items</h3>
                <ul className="list-disc space-y-1 pl-4 text-sm">
                  {fcast.watch_items!.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>

        {weekly && (hitRate || scorecard) ? (
          <Card>
            <CardHeader>
              <CardTitle>Forecast hit rate</CardTitle>
              <CardDescription>
                Does the stated confidence hold up?
                {hitRate ? ` · last ${hitRate.weeks} weeks` : ""}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {hitRate && <HitRateBlock hitRate={hitRate} />}
              {scorecard && (
                <>
                  <p className="text-sm">
                    Week {isoWeek(scorecard.reviewed.period_start)} scorecard:{" "}
                    {scorecard.events.length
                      ? scorecard.events.map((e) => `${e.id} ${VERDICT_WORD[effectiveVerdict(e)]}`).join(", ") + "."
                      : "no events."}
                  </p>
                  <Disclosure title="Review verdicts">
                    <ScorecardBlock recapId={doc.id} scorecard={scorecard} />
                  </Disclosure>
                </>
              )}
            </CardContent>
          </Card>
        ) : null}
      </div>

      <section>
        <h2 className="mb-1 font-heading text-lg font-semibold">More signals</h2>
        <Disclosure title="Week over week, top tweets and active campaigns" printOpen>
          <div className="space-y-6 pt-2">
            {quality.comparison && (
              <div>
                <h3 className="mb-2 text-sm font-semibold">Week over week</h3>
                <ComparisonBlock comparison={quality.comparison} />
              </div>
            )}
            <div>
              <h3 className="mb-2 text-sm font-semibold">
                Top tweets ({(recap.top_tweets ?? []).length})
              </h3>
              {recap.top_tweets?.length ? (
                <ul className="space-y-2">
                  {recap.top_tweets.map((t, i) => (
                    <li key={i} className="text-sm leading-snug">
                      <span className="font-code font-medium">@{t.author || "?"}</span>{" "}
                      <Badge
                        variant="outline"
                        className="border-primary/40 bg-primary/10 font-mono text-xs text-primary-text"
                      >
                        {t.signal || "other"}
                      </Badge>
                      {t.summary && <p className="mt-1">{t.summary}</p>}
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyNote />
              )}
            </div>
            <div>
              <h3 className="mb-2 text-sm font-semibold">
                Active campaigns ({(recap.active_campaigns ?? []).length})
              </h3>
              {recap.active_campaigns?.length ? (
                <ul className="space-y-2">
                  {recap.active_campaigns.map((c, i) => (
                    <li key={i} className="text-sm leading-snug">
                      <span className="font-medium">{c.theme || "(unlabeled)"}</span>{" "}
                      <span className="font-code text-xs text-muted-foreground">
                        · {c.article_count ?? 0} articles
                      </span>
                      {c.why_it_matters && (
                        <p className="mt-1 text-muted-foreground">{c.why_it_matters}</p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyNote />
              )}
            </div>
          </div>
        </Disclosure>
      </section>

      {doc.raw_llm && !isEmpty && (
        <Disclosure title="Raw LLM output (parse fallback)" printOpen>
          <pre className="mt-1.5 rounded-md border border-border p-2.5 text-xs whitespace-pre-wrap text-muted-foreground">
            {doc.raw_llm}
          </pre>
        </Disclosure>
      )}
    </div>
  );
}
