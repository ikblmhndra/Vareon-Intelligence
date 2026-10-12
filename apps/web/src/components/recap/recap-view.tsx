import { Badge } from "@/components/ui/badge";
import type { RecapDoc, RecapHitRate, RecapTopStory } from "@/lib/api/loose-types";
import { recapTitle } from "@/lib/recap/period";
import { safeHttpUrl } from "@/lib/recap/quality";
import { ConfidenceBadge, Chips, EmptyNote, Section } from "@/components/recap/recap-parts";
import {
  ComparisonBlock,
  GroundingBlock,
  HitRateBlock,
  ScorecardBlock,
} from "@/components/recap/recap-quality";

/** Judul cerita; bertaut ke artikelnya kalau ada `url` (cerita yang lolos grounding membawanya,
 * recap lama tidak: judulnya tampil polos seperti dulu). */
function StoryTitle({ story }: { story: RecapTopStory }) {
  const href = safeHttpUrl(story.url);
  if (!href) return <span className="font-medium">{story.title}</span>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="font-medium text-primary underline-offset-2 hover:underline"
    >
      {story.title}
    </a>
  );
}

/**
 * Render satu dokumen recap (harian atau mingguan) -- port `_recapRender()` di
 * `legacy/static/js/newsroom/recap.js`, ditulis pakai token Tailwind +
 * `Badge` shadcn gantiin string HTML inline-style manual. Isi recap mingguan juga ada di
 * `doc.yesterday` (nama kolom lama), bentuknya sama dengan yang harian.
 *
 * Kualitas (#21 PR 4): `doc.quality` membawa tiga blok opsional (perbandingan, grounding,
 * scorecard) dan `hitRate` datang dari amplop balasan; masing-masing dipasang hanya kalau
 * datanya ada, jadi recap lama (`quality` = `{}`) dan recap harian tampil seperti sebelumnya.
 */
export function RecapView({ doc, hitRate }: { doc: RecapDoc; hitRate?: RecapHitRate }) {
  const recap = doc.yesterday || {};
  const fcast = doc.forecast || {};
  const counts = doc.counts || {};
  const gen = doc.generated_at ? new Date(doc.generated_at).toLocaleString() : "—";
  const tokens = doc.token_usage?.total_tokens;
  const weekly = doc.kind === "weekly";
  const quality = doc.quality ?? {};

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-gradient-to-br from-primary/5 to-primary/[0.04] px-4 py-3">
        <div>
          <div className="mb-1 text-sm font-semibold text-muted-foreground">
            {recapTitle(doc.kind, doc.date, doc.period_start, doc.period_end)}
          </div>
          <div className="text-sm leading-snug">{doc.headline || "(no headline)"}</div>
          {weekly && (
            <div className="mt-1 text-xs text-muted-foreground">
              Monday–Sunday by UTC date (Monday 07:00 to Monday 07:00 WIB)
            </div>
          )}
        </div>
        <div className="text-right font-mono text-xs text-muted-foreground">
          <div>
            {counts.articles ?? 0} articles · {counts.tweets ?? 0} tweets
          </div>
          <div>
            {counts.cves ?? 0} CVEs · {counts.iocs ?? 0} IOCs · {counts.campaigns ?? 0} campaigns
          </div>
          <div className="mt-1">
            gen: {gen}
            {doc.token_usage?.skipped ? " · LLM skipped (no activity)" : ""}
            {tokens ? ` · ${tokens} tokens` : ""}
          </div>
        </div>
      </div>

      {quality.grounding && <GroundingBlock grounding={quality.grounding} />}

      {quality.comparison && <ComparisonBlock comparison={quality.comparison} />}

      <Section title="Summary">
        <p className="text-sm leading-relaxed">{recap.summary || "(no summary)"}</p>
      </Section>

      <Section title={`Top Stories (${(recap.top_stories ?? []).length})`}>
        {recap.top_stories?.length ? (
          <ul className="list-disc space-y-1.5 pl-4 text-sm leading-snug">
            {recap.top_stories.map((s, i) => (
              <li key={i}>
                <StoryTitle story={s} />{" "}
                <span className="font-mono text-xs text-muted-foreground">[{s.source || "?"}]</span>
                {s.why_it_matters && (
                  <div className="mt-1 text-sm text-muted-foreground">{s.why_it_matters}</div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyNote />
        )}
      </Section>

      <Section title={`Top Tweets (${(recap.top_tweets ?? []).length})`}>
        {recap.top_tweets?.length ? (
          <ul className="list-disc space-y-1.5 pl-4 text-sm leading-snug">
            {recap.top_tweets.map((t, i) => (
              <li key={i}>
                <span className="font-medium">@{t.author || "?"}</span>{" "}
                <Badge variant="outline" className="border-ring/40 bg-ring/10 font-mono text-xs text-ring">
                  {t.signal || "other"}
                </Badge>
                {t.summary && <div className="mt-1 text-sm">{t.summary}</div>}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyNote />
        )}
      </Section>

      <Section title="Active Threat Actors">
        <Chips items={recap.active_threat_actors} />
      </Section>

      <Section title="Notable CVEs">
        <Chips items={recap.notable_cves} />
      </Section>

      <Section title={`Active Campaigns (${(recap.active_campaigns ?? []).length})`}>
        {recap.active_campaigns?.length ? (
          <ul className="list-disc space-y-1.5 pl-4 text-sm leading-snug">
            {recap.active_campaigns.map((c, i) => (
              <li key={i}>
                <span className="font-medium">{c.theme || "(unlabeled)"}</span>{" "}
                <span className="font-mono text-xs text-muted-foreground">
                  · {c.article_count ?? 0} articles
                </span>
                {c.why_it_matters && (
                  <div className="mt-1 text-sm text-muted-foreground">{c.why_it_matters}</div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyNote />
        )}
      </Section>

      {(recap.apac_signals ?? []).length > 0 && (
        <Section title="APAC Signals">
          <ul className="list-disc space-y-1 pl-4 text-sm leading-snug">
            {recap.apac_signals!.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </Section>
      )}

      <div className="mt-6 rounded-md border border-warning/40 bg-warning/[0.04] px-4 py-3">
        <div className="mb-2 font-mono text-sm tracking-[0.12em] text-warning uppercase">
          ▲ Forecast · Next {weekly ? "1-2 Weeks" : "1-3 Days"}
        </div>
        <p className="mb-2 text-sm leading-relaxed">{fcast.summary || "(no forecast)"}</p>

        <div className="mb-1.5 text-sm font-semibold text-muted-foreground">
          Likely Events ({(fcast.likely_events ?? []).length})
        </div>
        {fcast.likely_events?.length ? (
          <ul className="list-disc space-y-2 pl-4 text-sm">
            {fcast.likely_events.map((e, i) => (
              <li key={i}>
                <span className="font-medium">{e.event}</span> <ConfidenceBadge confidence={e.confidence} />
                <div className="mt-1 text-sm text-muted-foreground">
                  <span className="font-mono text-xs uppercase">Basis:</span> {e.basis}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyNote />
        )}

        {(fcast.watch_items ?? []).length > 0 && (
          <>
            <div className="mt-3 mb-1.5 text-sm font-semibold text-muted-foreground">
              Watch Items
            </div>
            <ul className="list-disc space-y-1 pl-4 text-sm">
              {fcast.watch_items!.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </>
        )}
      </div>

      {quality.scorecard && <ScorecardBlock recapId={doc.id} scorecard={quality.scorecard} />}

      {hitRate && <HitRateBlock hitRate={hitRate} />}

      {doc.raw_llm && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm font-semibold text-muted-foreground">
            Raw LLM output (parse fallback)
          </summary>
          <pre className="mt-1.5 rounded-md border border-border p-2.5 text-sm whitespace-pre-wrap text-muted-foreground">
            {doc.raw_llm}
          </pre>
        </details>
      )}
    </div>
  );
}
