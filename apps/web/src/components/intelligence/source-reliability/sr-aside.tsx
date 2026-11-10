"use client";

import { useQuery } from "@tanstack/react-query";

import { gradeChipClass, useSrLabels } from "@/components/intelligence/source-reliability/sr-model";
import { Card } from "@/components/ui/card";
import { MeterBar } from "@/components/ui/meter-bar";
import { StatePanel } from "@/components/ui/state-panel";
import { api } from "@/lib/api/client";
import type { SrStats } from "@/lib/api/loose-types";
import { cn } from "@/lib/utils";

const GRADES = ["A", "B", "C", "D", "E", "F"] as const;

const GRADE_TONE = {
  A: "success",
  B: "success",
  C: "warning",
  D: "destructive",
  E: "destructive",
  F: "neutral",
} as const;

interface SrAsideProps {
  /** Filter Grade aktif ("all" = tanpa filter); baris yang cocok ditandai `aria-pressed`. */
  grade: string;
  onGradeChange: (grade: string) => void;
}

/** Kartu samping: sebaran grade (klik baris = pasang filter Grade) dan legenda kode Admiralty. */
export function SrAside({ grade, onGradeChange }: SrAsideProps) {
  const stats = useQuery({
    queryKey: ["intelligence", "sr-stats"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/sr/stats");
      if (error) throw error;
      return data as unknown as SrStats;
    },
  });
  const labels = useSrLabels();

  const counts = new Map((stats.data?.by_grade ?? []).map((g) => [g.grade, g.count]));
  const max = Math.max(1, ...counts.values());

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <div className="flex flex-col gap-3 px-5">
          <div>
            <h2 className="font-heading text-base font-semibold">Grade distribution</h2>
            <p className="text-xs text-muted-foreground">Reliability letter across all sources</p>
          </div>
          {stats.isPending && <StatePanel variant="loading" title="Loading distribution" className="py-6" />}
          {stats.isError && <StatePanel variant="error" title="Could not load the distribution" className="py-6" />}
          {stats.data && (
            <ul className="flex flex-col gap-1">
              {GRADES.map((g) => {
                const count = counts.get(g) ?? 0;
                const active = grade === g;
                return (
                  <li key={g}>
                    <button
                      type="button"
                      aria-pressed={active}
                      aria-label={`Grade ${g}, ${count} sources. ${active ? "Clear" : "Filter by"} grade ${g}`}
                      onClick={() => onGradeChange(active ? "all" : g)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left outline-none hover:bg-surface focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                        active && "bg-surface",
                      )}
                    >
                      <span
                        aria-hidden="true"
                        className={cn(
                          "inline-flex size-6 shrink-0 items-center justify-center rounded-[6px] text-2xs font-semibold",
                          gradeChipClass(g),
                        )}
                      >
                        {g}
                      </span>
                      <MeterBar
                        className="flex-1"
                        value={count}
                        max={max}
                        tone={GRADE_TONE[g]}
                        aria-label={`Grade ${g}: ${count} sources`}
                        label={<span className="inline-block w-8 text-right font-code">{count}</span>}
                      />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </Card>

      <Card>
        <div className="flex flex-col gap-3 px-5">
          <h2 className="font-heading text-base font-semibold">Reading an Admiralty code</h2>
          {labels.isPending && <StatePanel variant="loading" title="Loading legend" className="py-6" />}
          {labels.isError && <StatePanel variant="error" title="Could not load the legend" className="py-6" />}
          {labels.data && (
            <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
              <Legend title="Reliability" map={labels.data.reliability} />
              <Legend title="Credibility" map={labels.data.credibility} />
            </div>
          )}
          <p className="text-2xs text-muted-foreground">
            Grades set by an analyst override the automatic grade. &apos;Needs review&apos; lists auto-graded sources.
          </p>
        </div>
      </Card>
    </div>
  );
}

function Legend({ title, map }: { title: string; map: Record<string, string> }) {
  return (
    <div>
      <h3 className="mb-1 text-2xs font-bold tracking-[0.12em] text-muted-foreground uppercase">{title}</h3>
      <dl className="flex flex-col gap-1">
        {Object.entries(map)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <dt className="w-3 shrink-0 font-code font-semibold">{k}</dt>
              <dd className="text-muted-foreground">{v}</dd>
            </div>
          ))}
      </dl>
    </div>
  );
}
