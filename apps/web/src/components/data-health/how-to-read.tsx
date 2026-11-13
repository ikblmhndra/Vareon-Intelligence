import type { ReactNode } from "react";

import { ToneChip } from "@/components/data-health/tone-chip";
import { Disclosure } from "@/components/ui/disclosure";

function Item({ name, children }: { name: string; children: ReactNode }) {
  return (
    <li>
      <strong className="text-foreground">{name}</strong>: {children}
    </li>
  );
}

/** Legenda nada + ambang tiap area (DH1). `open` dikendalikan supaya tautan header "How to read this page"
 * membukanya; `printOpen` menjaga ambang tetap tercetak walau terlipat. */
export function HowToRead({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <section id="how-to-read" className="mt-6 scroll-mt-6 rounded-2xl surface-raised p-4 text-sm">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-xs text-muted-foreground">
        <span className="text-2xs font-semibold tracking-wide text-foreground uppercase">How to read this page</span>
        <span aria-hidden>·</span>
        <ToneChip tone="ok" /> nothing to do
        <span aria-hidden>·</span>
        <ToneChip tone="warn" /> slower than usual or waiting for a retry
        <span aria-hidden>·</span>
        <ToneChip tone="bad" /> a source or job is failing
      </p>
      <Disclosure printOpen open={open} onOpenChange={onOpenChange} title="Thresholds for every area" className="mt-2">
        <ul className="mt-2 list-disc space-y-1.5 pl-5 text-muted-foreground">
          <Item name="Pipeline">
            ACTION when the scheduler (beat) heartbeat is stale or missing; WATCH when any scraper needs attention (the statuses
            are explained on the Scrapers page).
          </Item>
          <Item name="Pipeline card">
            Fetched and new are sums over scraper runs started in the window; published counts articles first seen in the window.
          </Item>
          <Item name="Enrichment">
            ACTION when 10% or more of the articles processed in 7 days failed, or 5 or more failed in 24 hours; WATCH when failed
            jobs are still waiting for a retry. The failure figures count failed jobs by the time they were created (a snapshot of
            jobs still failed), not by when they failed. A job that waits for the model is not in the news feed until it is
            retried, accepted or rejected.
          </Item>
          <Item name="Enrich queue">
            WATCH at half of the backpressure limit, ACTION at the limit (scrapers then stop handing over new articles until the
            queue drains).
          </Item>
          <Item name="Celery queues">
            messages waiting in each broker queue; tasks already picked up by a worker are not counted.
          </Item>
          <Item name="Freshness">
            articles WATCH after 6 hours and ACTION after 24; tweets and new IOCs WATCH after 24 hours and ACTION after 72; the
            CVE check WATCH after 6 hours and ACTION after 24; ATT&amp;CK ACTION when a domain failed to sync and WATCH when a
            domain is more than 30 days old.
          </Item>
          <Item name="Coverage">
            how many articles (all time) name at least one country, threat actor or technique, and how many IOCs of each type were
            checked by at least one reputation provider (IOCs a provider cannot check, such as private IPs, do not count).
          </Item>
          <Item name="LLM">
            ACTION when the latest model call failed (the row shows the HTTP status, error type, task and age); OK once a call
            succeeds again. The queue rows show the circuit breaker (closed: calls go through; open: calls pause until the retry
            time; half-open: one test call at a time), how many classify and TTP jobs wait for the model, how many failed and the
            age of the oldest pending job; pending jobs drain by themselves once the model works. The table compares each task
            over 24 hours and 7 days; a dash means no value was recorded.
          </Item>
          <Item name="Calls per hour">
            failed = calls that ended in an error or an empty reply.
          </Item>
          <Item name="Relevance model">
            a small local classifier that decides whether a title is threat news before the LLM is asked. In shadow it only
            measures agreement with the LLM; once the gate is on, titles the model is confident about skip the LLM classify call,
            except for an audit sample that still goes to the LLM so agreement stays measurable. The gate turns itself off if
            agreement on the latest audit samples drops.
          </Item>
          <Item name="CVE ingest">
            the CVE List V5 mirror that feeds the CVE tracker. ACTION when the last sync is missing or older than 15 minutes; WATCH
            when the hourly reconcile has not run for 2 hours or last ended in an error. Off when the mirror is disabled.
          </Item>
          <Item name="Sigma rules">
            the SigmaHQ snapshot used by hunting packs. ACTION when no rules are loaded; WATCH when the snapshot is more than 60
            days old or the last refresh reported an error.
          </Item>
        </ul>
      </Disclosure>
    </section>
  );
}
