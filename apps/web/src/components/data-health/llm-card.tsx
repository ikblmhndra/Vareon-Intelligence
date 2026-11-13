"use client";

import Link from "next/link";
import { useState } from "react";

import { ToneChip } from "@/components/data-health/tone-chip";
import { BarSeries } from "@/components/ui/bar-series";
import { LegendRow } from "@/components/ui/legend-row";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { components } from "@/lib/api/schema";
import type { Tone } from "@/lib/data-health/tones";
import { browserZoneName, fmtAgo, fmtCompactAge, fmtDateTime, fmtTime } from "@/lib/format";
import { cn } from "@/lib/utils";

type Llm = components["schemas"]["LlmHealthOut"];

const WINDOWS = [
  { value: "24h", label: "24 h" },
  { value: "7d", label: "7 d" },
] as const;

const BREAKER: Record<Llm["queue"]["breaker"], { tone: Tone; text: string }> = {
  closed: { tone: "ok", text: "BREAKER CLOSED" },
  half_open: { tone: "warn", text: "BREAKER HALF-OPEN" },
  open: { tone: "bad", text: "BREAKER OPEN" },
};
const STATUS: Record<Llm["status"], { tone: Tone; text: string }> = {
  ok: { tone: "ok", text: "STATUS OK" },
  failing: { tone: "bad", text: "STATUS FAILING" },
  unknown: { tone: "unknown", text: "STATUS UNKNOWN" },
};

const CELL = "px-2 py-1.5 text-xs sm:text-sm";
const HEAD = "h-8 px-2 text-2xs";
const NUM = cn(CELL, "text-right tabular-nums whitespace-nowrap");
const num = (n: number | null | undefined, unit = "") => (n === null || n === undefined ? "–" : `${n.toLocaleString()}${unit}`);

/** "503 timeout · classify · 5 m ago" tanpa bagian null; `title` memuat stempel waktu penuh. */
function errorText(e: NonNullable<Llm["last_error"]>, nowMs: number): string {
  const parts = [[e.http_status, e.error_type].filter((x) => x !== null).join(" ") || null, e.task, fmtAgo(e.at, nowMs)];
  return `Last error: ${parts.filter(Boolean).join(" · ")}`;
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg bg-surface px-3 py-2">
      <p className="text-2xs font-semibold tracking-wide text-muted-foreground uppercase">{label}</p>
      <p className="font-code text-lg font-semibold text-foreground tabular-nums">{value}</p>
      {sub && <p className="text-2xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

/** Kartu LLM gateway: breaker, antrean job, status panggilan terakhir, grafik panggilan per jam (UTC,
 * ditampilkan di zona browser) dan tabel pemakaian per tugas. "Sekarang" datang dari queryFn (`nowMs`). */
export function LlmCard({ llm, nowMs }: { llm: Llm; nowMs: number }) {
  const [win, setWin] = useState<(typeof WINDOWS)[number]["value"]>("24h");
  const q = llm.queue;
  const br = BREAKER[q.breaker];
  const st = STATUS[llm.status];
  const le = llm.last_error;

  const hours = llm.calls_per_hour;
  const hasCalls = hours.some((h) => h.ok + h.failed > 0);

  const usage = new Map((win === "24h" ? llm.usage_24h : llm.usage_7d).map((u) => [u.task, u]));
  const tasks = [...new Set([...llm.usage_24h.map((u) => u.task), ...llm.usage_7d.map((u) => u.task)])].sort();

  return (
    <section className="surface-raised mb-4 rounded-2xl p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-heading text-xl font-bold tracking-tight text-foreground">LLM gateway</h2>
          <p className="text-xs text-muted-foreground">Persist first: articles land without the model, jobs wait here</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ToneChip tone={br.tone}>{br.text}</ToneChip>
          {q.breaker === "open" && q.retry_at && (
            <span className="text-xs text-muted-foreground">retry at {fmtTime(q.retry_at)}</span>
          )}
          <ToneChip tone={st.tone}>{st.text}</ToneChip>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Pending classify" value={q.pending_classify.toLocaleString()} />
        <Stat label="Pending TTP" value={q.pending_ttp.toLocaleString()} />
        <Stat label="Failed" value={q.failed.toLocaleString()} />
        <Stat
          label="Oldest pending"
          value={q.oldest_pending_at ? fmtCompactAge(q.oldest_pending_at, nowMs) : "none"}
          sub={q.oldest_pending_at ? `since ${fmtTime(q.oldest_pending_at)} ${browserZoneName()}` : undefined}
        />
      </div>

      <div className="mt-3 space-y-0.5 text-sm">
        {llm.status === "failing" ? (
          <p title={le ? fmtDateTime(le.at) : undefined} className="text-destructive-text">
            {le ? errorText(le, nowMs) : "Last error: latest call returned no choices"}
          </p>
        ) : llm.status === "ok" ? (
          <>
            <p title={fmtDateTime(llm.last_ok_at)} className="text-foreground">
              Last successful call {fmtAgo(llm.last_ok_at, nowMs)}
            </p>
            {le && (
              <p title={fmtDateTime(le.at)} className="text-xs text-muted-foreground">
                {errorText(le, nowMs)}
              </p>
            )}
          </>
        ) : (
          <p className="text-muted-foreground">No calls recorded yet</p>
        )}
        <Link
          href="/newsroom"
          className="inline-block rounded-sm text-sm font-medium text-primary-text underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
        >
          Review jobs in Newsroom › Filtered Articles › Enrichment queue
        </Link>
      </div>

      <h3 className="mt-5 mb-2 text-2xs font-semibold tracking-wide text-muted-foreground uppercase">
        Calls per hour, last 24 h
      </h3>
      {hasCalls ? (
        <>
          <BarSeries
            aria-label="LLM calls per hour, last 24 hours"
            labels={hours.map((h, i) => (i === 23 ? "now" : fmtTime(h.hour)))}
            values={hours.map((h) => h.ok)}
            valueLabel="ok"
            tone="primary"
            stackValues={hours.map((h) => h.failed)}
            stackLabel="failed"
            tickEvery={6}
          />
          {/* Kotak legenda memakai token yang sama dengan batang: primary dan severity-critical (t.critical). */}
          <LegendRow
            items={[
              { label: "ok", swatchClass: "bg-primary" },
              { label: "failed (error or empty reply)", swatchClass: "bg-severity-critical" },
            ]}
          />
          <p className="mt-1 text-2xs text-muted-foreground">
            Hours are UTC clock hours shown in {browserZoneName()}; the last bar is the current hour so far.
          </p>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">No LLM calls in the last 24 hours.</p>
      )}

      <div className="mt-5 mb-2 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-2xs font-semibold tracking-wide text-muted-foreground uppercase">Usage by task</h3>
        <SegmentedControl size="sm" aria-label="Usage window" options={WINDOWS} value={win} onChange={setWin} />
      </div>
      <Table className="table-fixed">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className={cn(HEAD, "w-[22%]")}>TASK, {win === "24h" ? "24 H" : "7 D"}</TableHead>
            <TableHead className={cn(HEAD, "w-[12%] text-right")}>CALLS</TableHead>
            <TableHead className={cn(HEAD, "w-[12%] text-right")}>ERRORS</TableHead>
            <TableHead className={cn(HEAD, "w-[15%] text-right")}>PROMPT TOK</TableHead>
            <TableHead className={cn(HEAD, "w-[15%] text-right")}>COMPLETION TOK</TableHead>
            <TableHead className={cn(HEAD, "w-[12%] text-right")}>P50 LATENCY</TableHead>
            <TableHead className={cn(HEAD, "w-[12%] text-right")}>PROMPT</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tasks.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={7} className="px-2 py-3 text-sm text-muted-foreground">
                No LLM calls recorded in the last 7 days.
              </TableCell>
            </TableRow>
          ) : (
            tasks.map((task) => {
              const u = usage.get(task);
              return (
                <TableRow key={task}>
                  <TableCell className={cn(CELL, "truncate font-code")} title={task}>
                    {task}
                  </TableCell>
                  <TableCell className={NUM}>{num(u?.calls)}</TableCell>
                  <TableCell className={NUM}>{num(u?.errors)}</TableCell>
                  <TableCell className={NUM}>{num(u?.prompt_tokens)}</TableCell>
                  <TableCell className={NUM}>{num(u?.completion_tokens)}</TableCell>
                  <TableCell className={NUM}>{num(u?.median_latency_ms, " ms")}</TableCell>
                  <TableCell className={cn(NUM, "font-code")}>{u?.prompt_version ?? "–"}</TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>
    </section>
  );
}
