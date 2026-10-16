"use client";

import { useRouter } from "next/navigation";

import { cn } from "@/lib/utils";
import { taConfidenceColor } from "@/lib/exec/format";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

function toTitleCase(s: string): string {
  return s.replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
}

/** Port TA Leaderboard (`exec.js:169-196`). Klik row = `drillToNewsroomTA()`
 * di legacy (ganti tab + auto-pilih filter actor + reload panel) --
 * `/newsroom` di sini gak addressable lewat query param (filter state-nya
 * lokal ke komponen, lihat Grup D), jadi klik cuma pindah rute ke
 * `/newsroom` polos, TANPA auto-filter. Gap kecil, dicatat di
 * docs/PROGRESS.md, bukan pura-pura jalan penuh. */
export function TaLeaderboard({ d }: { d: ExecDashboardV2 }) {
  const router = useRouter();
  const prevSet = new Set(d.prev_ta_names.map((n) => n.toLowerCase()));
  const taConf = d.ta_confidence;
  const maxTa = d.ta_leaderboard[0]?.count || 1;
  // NEW/REC membandingkan dengan periode sebelumnya; kalau itu kosong, semua aktor "NEW" = noise.
  const showStatus = d.prev_period_reliable;

  return (
    <div className="space-y-1.5 rounded-2xl surface-raised p-5">
      {d.ta_leaderboard.map((ta) => {
        const isNew = !prevSet.has(ta.name.toLowerCase());
        const conf = taConf[ta.name] ?? taConf[ta.name.toLowerCase()] ?? null;
        const confColor = taConfidenceColor(conf);
        const pct = Math.round((ta.count / maxTa) * 100);
        return (
          <button
            key={ta.name}
            className="flex w-full items-center gap-2 text-left"
            title={`${toTitleCase(ta.name)} — Click to view in News Room\nSignal Quality: ${conf !== null ? conf + "% of mentions are incident-type articles" : "unknown"}`}
            onClick={() => router.push("/newsroom")}
          >
            <span className="flex min-w-0 flex-1 items-center gap-1 truncate font-mono text-xs text-foreground">
              {toTitleCase(ta.name)}
              {showStatus && (
                <span
                  className={cn(
                    "shrink-0 rounded px-1 py-0.5 text-xs",
                    isNew ? "bg-success/20 text-success" : "bg-muted text-muted-foreground",
                  )}
                >
                  {isNew ? "NEW" : "REC"}
                </span>
              )}
            </span>
            <div className="mx-2 h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary/60" style={{ width: `${pct}%` }} />
            </div>
            <span className="font-mono text-xs text-muted-foreground">{ta.count}</span>
            <span
              className={cn("ml-auto shrink-0 rounded px-1 py-0.5 font-mono text-xs", confColor, confColor.replace("text-", "bg-") + "/15")}
              title="Signal quality: % of articles classified as incident type"
            >
              {conf === null ? "?" : `${conf}%`}
            </span>
          </button>
        );
      })}
    </div>
  );
}
