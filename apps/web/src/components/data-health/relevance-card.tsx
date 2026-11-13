"use client";

import type { ReactNode } from "react";

import { Chip } from "@/components/ui/chip";
import { MeterBar } from "@/components/ui/meter-bar";
import { Notice } from "@/components/ui/notice";
import type { components } from "@/lib/api/schema";
import { fmtShortDate } from "@/lib/format";

type Rel = components["schemas"]["RelevanceHealthOut"];

/** Pecahan 0-1 dari API jadi persen satu desimal ("96.4%"); null jadi "–". */
const pc = (x: number | null): string => (x === null ? "–" : `${(x * 100).toFixed(1)}%`);

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right text-sm text-foreground tabular-nums">{children}</dd>
    </div>
  );
}

/** Kartu model relevansi lokal. Tiga varian (DH8): mode off, belum ada model aktif (`gate_state` null),
 * dan model aktif dengan gauge + baris detail; notice shadow/gate-mati di atas baris bila perlu. */
export function RelevanceCard({ rel }: { rel: Rel }) {
  const avoided = (
    <Row label="Classify calls avoided">
      {rel.classify_avoided_24h.toLocaleString()} / 24 h · {rel.classify_avoided_7d.toLocaleString()} / 7 d
    </Row>
  );
  const since = rel.gate_changed_at ? ` since ${fmtShortDate(rel.gate_changed_at)}` : "";

  return (
    <section className="surface-raised mb-4 rounded-2xl p-5">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="font-heading text-xl font-bold tracking-tight text-foreground">Relevance model</h2>
          <p className="text-xs text-muted-foreground">Local model decides before the LLM does</p>
        </div>
        <Chip kind="flag" value={rel.mode}>
          {rel.mode.toUpperCase()}
        </Chip>
      </div>

      {rel.mode === "off" ? (
        <>
          <Notice title="The relevance model is off">Every title goes to the LLM classify call.</Notice>
          <dl className="mt-2 divide-y divide-border/70">{avoided}</dl>
        </>
      ) : rel.gate_state === null ? (
        <>
          <Notice title="No active model yet">
            Until a model is trained and activated, every title goes to the LLM classify call.
          </Notice>
          <dl className="mt-2 divide-y divide-border/70">{avoided}</dl>
        </>
      ) : (
        <>
          <div className="mb-3">
            <p className="text-2xl font-semibold text-foreground tabular-nums">
              {pc(rel.holdout_agreement)}{" "}
              <span className="text-sm font-normal text-muted-foreground">holdout agreement</span>
            </p>
            {rel.holdout_agreement !== null && (
              <MeterBar
                aria-label="Holdout agreement"
                value={Math.round(rel.holdout_agreement * 1000) / 10}
                max={100}
                tone="primary"
                className="mt-2"
              />
            )}
          </div>
          {rel.mode === "shadow" ? (
            <Notice
              title="Shadow: the model only measures agreement with the LLM; no classify call is skipped."
              className="mb-2"
            />
          ) : (
            rel.gate_state === "shadow" && (
              <Notice
                title="Gate is off: agreement is being measured, or the gate turned itself off after audit agreement dropped."
                className="mb-2"
              />
            )
          )}
          <dl className="divide-y divide-border/70">
            <Row label="Gate">{rel.gate_state === "gate" ? `on${since}` : `off (shadow)${since}`}</Row>
            <Row label="Model trained">
              {fmtShortDate(rel.model_trained_at)} · {(rel.n_examples ?? 0).toLocaleString()} examples
            </Row>
            <Row label="Holdout band share">{pc(rel.holdout_band_share)}</Row>
            <Row label="Band agreement 14 d">
              {rel.band_titles_14d === 0
                ? "no in-band titles with an LLM verdict yet"
                : `${pc(rel.band_agreement_14d)} of ${rel.band_titles_14d.toLocaleString()}`}
            </Row>
            <Row label="Middle band 14 d">{rel.middle_band_14d.toLocaleString()} → LLM</Row>
            <Row label="Audit samples">
              {rel.audit_samples === 0 ? "none yet" : `${rel.audit_samples.toLocaleString()} · ${pc(rel.audit_agreement)}`}
            </Row>
            {avoided}
          </dl>
        </>
      )}
    </section>
  );
}
