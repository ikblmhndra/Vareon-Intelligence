"use client";

import { Chip } from "@/components/ui/chip";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Notice } from "@/components/ui/notice";
import type { components } from "@/lib/api/schema";
import { epssColorClass } from "@/lib/cve/format";
import { fmtShortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

type CveLookupOut = components["schemas"]["CveLookupOut"];
type LookupSource = components["schemas"]["LookupSource"];

const SOURCE_LABEL: Record<LookupSource["id"], string> = {
  mirror: "CVE List V5 mirror",
  nvd: "NVD",
  circl: "CIRCL",
  exploitdb: "Exploit-DB",
  epss: "EPSS",
};

const STATUS_LABEL: Record<LookupSource["status"], string> = {
  ok: "ok",
  not_found: "not found",
  error: "error",
  timeout: "timeout",
  rate_limited: "rate limited",
  cached: "cached",
};

const STATUS_TONE: Record<LookupSource["status"], "ok" | "watch" | "action" | null> = {
  ok: "ok",
  cached: "ok",
  not_found: null,
  timeout: "watch",
  rate_limited: "watch",
  error: "action",
};

const SEVERITIES = ["critical", "high", "medium", "low"] as const;

function SourceChip({ s }: { s: LookupSource }) {
  const label = `${SOURCE_LABEL[s.id]} ${STATUS_LABEL[s.status]}`;
  const tone = STATUS_TONE[s.status];
  return tone ? <Chip kind="status" value={tone}>{label}</Chip> : <Chip kind="flag" value={label} />;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-2xs font-semibold uppercase text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

/** Teks sumber luar (NVD/Exploit-DB) kadang membawa entitas HTML ("&lt;"). Decode sebagai TEKS saja lewat
 * DOMParser (tidak mengeksekusi skrip, bukan innerHTML); di SSR dikembalikan apa adanya. */
function decodeEntities(s: string): string {
  if (typeof DOMParser === "undefined" || !s.includes("&")) return s;
  return new DOMParser().parseFromString(s, "text/html").documentElement.textContent ?? s;
}

/** Hanya tautan http(s): data berasal dari sumber luar (NVD/CIRCL/Exploit-DB). */
function safeHref(url: string): string | null {
  return /^https?:\/\//i.test(url) ? url : null;
}

/** Hasil `GET /api/cve/lookup/{id}` (spec 2a 6.9): judul = id CVE, chip severity, status tiap sumber, ringkasan,
 * vector, kotak KEV, EPSS, exploit, referensi, dan catatan apakah CVE terlacak di client ini. */
export function LookupResultDialog({
  result,
  onOpenChange,
}: {
  result: CveLookupOut | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={result !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">{result && <LookupBody r={result} />}</DialogContent>
    </Dialog>
  );
}

function LookupBody({ r }: { r: CveLookupOut }) {
  const sevKey = (r.cvss_severity ?? "").toLowerCase();
  const sev = (SEVERITIES as readonly string[]).includes(sevKey) ? (sevKey as (typeof SEVERITIES)[number]) : "unrated";
  const exploits = r.exploits ?? [];
  const refs = r.references ?? [];
  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex flex-wrap items-center gap-2">
          <span className="font-code">{r.cve_id}</span>
          <Chip kind="severity" value={sev}>
            {r.cvss_severity ? `${r.cvss_severity} ${r.cvss_score ?? ""}`.trim() : "Unrated"}
          </Chip>
          {r.tracked && <Chip kind="cve" value="monitored">Tracked</Chip>}
          {r.false_positive && <Chip kind="cve" value="false_positive" />}
          {r.kev && <Chip kind="cve" value="kev" />}
        </DialogTitle>
        <DialogDescription>
          Published {fmtShortDate(r.published)} - modified {fmtShortDate(r.modified)}
        </DialogDescription>
      </DialogHeader>

      {r.sources && r.sources.length > 0 && (
        <div className="flex flex-wrap gap-1.5" aria-label="Source status">
          {r.sources.map((s) => (
            <SourceChip key={s.id} s={s} />
          ))}
        </div>
      )}

      <Section title="Summary">
        <p className="text-sm">{decodeEntities(r.summary) || "No summary available."}</p>
      </Section>

      {r.cvss_vector && (
        <Section title="CVSS vector">
          <p className="font-code text-xs break-all">{r.cvss_vector}</p>
        </Section>
      )}

      {r.kev && (
        <div className="rounded-lg bg-destructive/10 px-4 py-3 text-xs">
          <p className="font-semibold text-destructive-text">On the CISA KEV catalog</p>
          <p className="mt-1 text-muted-foreground">
            Added {fmtShortDate(r.kev.added)} - due {fmtShortDate(r.kev.due)}
          </p>
          {r.kev.action && <p className="mt-1 text-foreground">{decodeEntities(r.kev.action)}</p>}
        </div>
      )}

      {r.epss_score != null && (
        <Section title="EPSS">
          <p className="text-sm">
            <span className={cn("font-semibold", epssColorClass(r.epss_score))}>{(r.epss_score * 100).toFixed(2)}%</span>
            {r.epss_percentile != null && (
              <span className="text-muted-foreground"> - percentile {(r.epss_percentile * 100).toFixed(1)}</span>
            )}
          </p>
        </Section>
      )}

      <Section title={`Exploits (${exploits.length})`}>
        {exploits.length === 0 ? (
          <p className="text-xs text-muted-foreground">No public exploits found.</p>
        ) : (
          <ul className="flex flex-col gap-1 text-xs">
            {exploits.map((x, i) => {
              const href = safeHref(x.url);
              return (
                <li key={`${i}-${x.url}`}>
                  {href ? (
                    <a href={href} target="_blank" rel="noreferrer noopener" className="text-primary-text underline underline-offset-2">
                      {decodeEntities(x.title)}
                    </a>
                  ) : (
                    decodeEntities(x.title)
                  )}
                  {x.published && <span className="text-muted-foreground"> - {fmtShortDate(x.published)}</span>}
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      {refs.length > 0 && (
        <Section title={`References (${refs.length})`}>
          <ul className="flex max-h-32 flex-col gap-1 overflow-y-auto text-xs">
            {refs.map((u, i) => {
              const href = safeHref(u);
              return (
                <li key={`${i}-${u}`} className="break-all">
                  {href ? (
                    <a href={href} target="_blank" rel="noreferrer noopener" className="text-primary-text underline underline-offset-2">
                      {u}
                    </a>
                  ) : (
                    u
                  )}
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      {r.tracked ? (
        <Notice tone="info" title="Tracked in this client">
          {r.tracker_tech ? `Matched to ${r.tracker_tech}.` : "This CVE is in the tracker."}
        </Notice>
      ) : (
        <Notice title="Not in this client's tracker">Looking it up does not add it to the tracker.</Notice>
      )}
    </>
  );
}
