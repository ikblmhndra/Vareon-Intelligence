"use client";

import { useMemo, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

import { useRubricCounts } from "@/components/newsroom/all-articles-queries";
import { RUBRIC_TITLES, type RubricKey } from "@/components/newsroom/rubric-queries";
import { useDashboardStats } from "@/components/dashboard/use-dashboard-overview";
import { Checkbox } from "@/components/ui/checkbox";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";
import { useCan } from "@/lib/auth/permissions";
import { countryName } from "@/lib/dashboard/countries";
import { parseLocalDate } from "@/lib/format";
import { GRADE_BADGE_CLASS } from "@/lib/intelligence/format";
import { RESET_PATCH, type AllState, type Grade } from "@/lib/newsroom/all-state";
import { useFilterOptions } from "@/lib/newsroom/filters";
import { NEWSROOM_PERIODS, newsroomPeriodInfo, type NewsroomPeriod } from "@/lib/newsroom/period";
import { noClientRetry, unwrap } from "@/lib/scrapers/queries";
import { cn } from "@/lib/utils";

const ALL = "__all__";
const ADD = "__add__";
const GRADES: readonly Grade[] = ["A", "B", "C", "D", "E", "F"];
const PERIOD_OPTIONS = NEWSROOM_PERIODS.map((p) => ({ value: p.key, label: p.label }));
const FOCUS =
  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none";

/** Teks Admiralty per huruf. Tabel nilai per huruf belum ada di `score-reasons.ts` (hanya baris
 * per artikel), jadi baku NATO/Admiralty dipasang di sini sebagai `title`. */
const GRADE_TEXT: Record<Grade, string> = {
  A: "A: completely reliable source",
  B: "B: usually reliable source",
  C: "C: fairly reliable source",
  D: "D: not usually reliable source",
  E: "E: unreliable source",
  F: "F: reliability cannot be judged",
};

/** Urutan baris rubrik; "All news" = tanpa rubrik. Judul rail memakai kata pendek ("Ransomware"). */
const RUBRIC_ROWS: { key: RubricKey | null; label: string }[] = [
  { key: null, label: "All news" },
  { key: "apac", label: RUBRIC_TITLES.apac },
  { key: "global", label: RUBRIC_TITLES.global },
  { key: "local", label: RUBRIC_TITLES.local },
  { key: "ransomware", label: "Ransomware" },
  { key: "watchlist", label: "Watchlist" },
  { key: "techstack", label: "Tech stack" },
];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-2xs font-semibold tracking-wider text-muted-foreground uppercase">{title}</h2>
      {children}
    </section>
  );
}

function Count({ value }: { value: number | null | undefined }) {
  if (value === undefined) return <Skeleton aria-hidden className="h-3.5 w-8" />;
  return <span className="font-code text-2xs text-muted-foreground">{value === null ? "–" : value.toLocaleString("en-US")}</span>;
}

/** Pilihan group/industri korban; kunci cache sama dengan sheet lama. Hanya dimuat saat rubrik
 * Ransomware aktif dan pemakai punya `view_intel`. */
function useVictimFilterOptions(enabled: boolean) {
  return useQuery({
    queryKey: ["ransomware", "victim-filters"],
    queryFn: async () =>
      unwrap(await api.GET("/api/ransomware/victims/filters"), "The request failed.") as unknown as {
        groups: string[];
        industries: string[];
      },
    enabled,
    staleTime: 5 * 60_000,
    retry: noClientRetry,
  });
}

/** Rail filter All articles (spec 6.2, 236 px). Semua kendali hanya memanggil `onChange(patch)`;
 * penulisan URL milik pemanggil. */
export function AllRail({ state, onChange }: { state: AllState; onChange: (patch: Partial<AllState>) => void }) {
  const can = useCan();
  const counts = useRubricCounts(state);
  const options = useFilterOptions();
  const victims = state.rubric === "ransomware" && can("view_intel");
  const victimOptions = useVictimFilterOptions(victims);

  // Jumlah hari untuk top sources: periode, atau `from` sampai hari ini (inklusif). Jam dibaca di
  // useMemo, bukan di badan render.
  const days = useMemo(() => {
    if (!state.from) return newsroomPeriodInfo(state.period).days;
    const start = parseLocalDate(state.from);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.max(Math.round((today.getTime() - start.getTime()) / 86_400_000) + 1, 1);
  }, [state.from, state.period]);
  const stats = useDashboardStats(days, false);

  const rows = RUBRIC_ROWS.filter(
    (r) =>
      (r.key !== "ransomware" || can("view_intel")) &&
      (r.key !== "watchlist" || can("view_ta")) &&
      (r.key !== "techstack" || can("view_cve")),
  );

  const countryCodes = (options.data?.countries ?? []).filter((c) => !state.countries.includes(c));
  const countryItems: Record<string, string> = {
    [ADD]: "Add a country",
    ...Object.fromEntries(countryCodes.map((c) => [c, countryName(c)])),
  };
  const industries = options.data?.industries ?? [];
  const sectorList = state.sector && !industries.includes(state.sector) ? [state.sector, ...industries] : industries;
  const sectorItems: Record<string, string> = {
    [ALL]: "All sectors",
    ...Object.fromEntries(sectorList.map((s) => [s, s])),
  };

  // Sumber dari URL di luar top 10: tampil dulu, tercentang, tanpa hitungan (aturan 3).
  const top = stats.data?.top_sources ?? [];
  const topNames = new Set(top.map((s) => s.name));
  const extra = state.sources.filter((s) => !topNames.has(s));

  const toggleGrade = (g: Grade) =>
    onChange({ grades: GRADES.filter((x) => (x === g ? !state.grades.includes(g) : state.grades.includes(x))) });
  const toggleSource = (name: string) =>
    onChange({ sources: state.sources.includes(name) ? state.sources.filter((s) => s !== name) : [...state.sources, name] });

  const hint = victims ? <span className="text-2xs text-muted-foreground">Not used for victims</span> : null;

  return (
    <aside aria-label="Filters" className="w-full space-y-5 lg:w-[236px] lg:shrink-0">
      <Section title="Period">
        <SegmentedControl<NewsroomPeriod | "none">
          aria-label="Period"
          options={PERIOD_OPTIONS}
          value={state.from ? "none" : state.period}
          onChange={(v) => v !== "none" && onChange({ period: v })}
        />
        <label className={cn("flex items-center gap-2 text-xs text-foreground", victims && "text-muted-foreground")}>
          <Checkbox
            checked={state.incidents}
            disabled={victims}
            onCheckedChange={(v) => onChange({ incidents: v === true })}
          />
          Incidents only
        </label>
        {hint}
      </Section>

      <Section title="Rubric">
        <ul className="space-y-0.5">
          {rows.map((r) => {
            const active = state.rubric === r.key;
            return (
              <li key={r.key ?? "all"}>
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => onChange({ rubric: r.key })}
                  className={cn(
                    "flex w-full items-center justify-between rounded-md px-2 py-1 text-left text-xs text-foreground hover:bg-surface",
                    active && "bg-surface font-semibold",
                    FOCUS,
                  )}
                >
                  {r.label}
                  <Count value={counts[r.key ?? "all"]} />
                </button>
              </li>
            );
          })}
        </ul>
      </Section>

      <Section title="Source reliability">
        <div role="group" aria-label="Source reliability" className="flex gap-1">
          {GRADES.map((g) => {
            const on = state.grades.includes(g);
            return (
              <button
                key={g}
                type="button"
                aria-pressed={on}
                disabled={victims}
                title={GRADE_TEXT[g]}
                onClick={() => toggleGrade(g)}
                className={cn(
                  "grid size-7 place-content-center rounded-md border font-code text-xs disabled:cursor-not-allowed disabled:text-muted-foreground disabled:opacity-60",
                  GRADE_BADGE_CLASS[g],
                  on && "bg-surface font-semibold ring-1 ring-current",
                  FOCUS,
                )}
              >
                {g}
              </button>
            );
          })}
        </div>
        {hint}
      </Section>

      <Section title="Country">
        <Select
          items={countryItems}
          value={ADD}
          onValueChange={(v) => v && v !== ADD && onChange({ countries: [...state.countries, v] })}
        >
          <SelectTrigger aria-label="Add a country" className="w-full text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ADD} className="text-xs">
              Add a country
            </SelectItem>
            {countryCodes.map((c) => (
              <SelectItem key={c} value={c} className="text-xs">
                {countryName(c)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {state.countries.length > 0 && (
          <ul className="flex flex-wrap gap-1">
            {state.countries.map((c) => (
              <li
                key={c}
                className="inline-flex items-center gap-1 rounded-full bg-panel py-0.5 pr-0.5 pl-2.5 text-xs text-foreground"
              >
                {countryName(c)}
                <button
                  type="button"
                  aria-label={`Remove ${countryName(c)}`}
                  onClick={() => onChange({ countries: state.countries.filter((x) => x !== c) })}
                  className={cn("grid size-5 place-content-center rounded-full hover:bg-muted", FOCUS)}
                >
                  <X className="size-3" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Sector">
        <Select
          items={sectorItems}
          value={state.sector ?? ALL}
          disabled={victims}
          onValueChange={(v) => onChange({ sector: !v || v === ALL ? null : v })}
        >
          <SelectTrigger aria-label="Sector" className="w-full text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL} className="text-xs">
              All sectors
            </SelectItem>
            {sectorList.map((s) => (
              <SelectItem key={s} value={s} className="text-xs">
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {hint}
      </Section>

      {victims && (
        <Section title="Ransomware">
          {(
            [
              { key: "group" as const, label: "Group", all: "All groups", values: victimOptions.data?.groups ?? [] },
              {
                key: "vindustry" as const,
                label: "Industry",
                all: "All industries",
                values: victimOptions.data?.industries ?? [],
              },
            ] as const
          ).map((f) => {
            const current = state[f.key];
            const list = current && !f.values.includes(current) ? [current, ...f.values] : f.values;
            return (
              <Select
                key={f.key}
                items={{ [ALL]: f.all, ...Object.fromEntries(list.map((v) => [v, v])) }}
                value={current ?? ALL}
                onValueChange={(v) => onChange({ [f.key]: !v || v === ALL ? null : v })}
              >
                <SelectTrigger aria-label={`Victim ${f.label.toLowerCase()}`} className="w-full text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL} className="text-xs">
                    {f.all}
                  </SelectItem>
                  {list.map((v) => (
                    <SelectItem key={v} value={v} className="text-xs">
                      {v}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            );
          })}
        </Section>
      )}

      <Section title="Sources">
        {stats.isLoading ? (
          <div aria-hidden className="space-y-1.5">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-4 w-full" />
            ))}
          </div>
        ) : stats.isError && extra.length === 0 ? (
          <p className="text-xs text-muted-foreground">Could not load sources.</p>
        ) : (
          <ul className="space-y-1">
            {[...extra.map((name) => ({ name, count: null as number | null })), ...top].map((s) => (
              <li key={s.name}>
                <label
                  className={cn(
                    "flex items-center gap-2 text-xs text-foreground",
                    victims && "text-muted-foreground",
                  )}
                >
                  <Checkbox
                    checked={state.sources.includes(s.name)}
                    disabled={victims}
                    onCheckedChange={() => toggleSource(s.name)}
                  />
                  <span className="min-w-0 flex-1 truncate">{s.name}</span>
                  {s.count !== null && <span className="font-code text-2xs text-muted-foreground">{s.count.toLocaleString("en-US")}</span>}
                </label>
              </li>
            ))}
          </ul>
        )}
        <span className="block text-2xs text-muted-foreground">Counts are in period</span>
        {hint}
      </Section>

      <button
        type="button"
        onClick={() => onChange(RESET_PATCH)}
        className={cn("rounded-md px-2 py-1 text-xs font-medium text-primary-text hover:underline", FOCUS)}
      >
        Reset filters
      </button>
    </aside>
  );
}
