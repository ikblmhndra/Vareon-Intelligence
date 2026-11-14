"use client";

import { X } from "lucide-react";

import type { RubricKey } from "@/components/newsroom/rubric-queries";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useCan } from "@/lib/auth/permissions";
import { countryName } from "@/lib/dashboard/countries";
import { fmtShortDate } from "@/lib/format";
import { useFilterOptions } from "@/lib/newsroom/filters";
import { NEWSROOM_PERIODS, type NewsroomPeriod, type NewsroomUi } from "@/lib/newsroom/period";

const ALL = "__all__";
const PERIOD_OPTIONS = NEWSROOM_PERIODS.map((p) => ({ value: p.key, label: p.label }));

/** Judul rubrik di select dan di sheet ("Ransomware victims", bukan "Ransomware"). */
const RUBRIC_OPTIONS: { value: RubricKey; label: string }[] = [
  { value: "apac", label: "APAC" },
  { value: "global", label: "Global" },
  { value: "local", label: "Local" },
  { value: "ransomware", label: "Ransomware victims" },
  { value: "watchlist", label: "Watchlist" },
  { value: "techstack", label: "Tech stack" },
];

/** Baris filter halaman depan: pencarian, periode, negara, rubrik, insiden, chip `from`.
 * Semua kendali berlaku langsung; URL ditulis oleh `onChange` milik NewsroomView. */
export function FilterBar({
  ui,
  searchText,
  onSearchText,
  onChange,
}: {
  ui: NewsroomUi;
  searchText: string;
  onSearchText: (v: string) => void;
  onChange: (p: Partial<NewsroomUi>) => void;
}) {
  const can = useCan();
  const options = useFilterOptions();
  const countries = options.data?.countries ?? [];
  // Negara dari URL yang tak ada di daftar tetap tampil dengan namanya.
  const codes = ui.country && !countries.includes(ui.country) ? [ui.country, ...countries] : countries;
  const countryItems: Record<string, string> = {
    [ALL]: "All countries",
    ...Object.fromEntries(codes.map((c) => [c, countryName(c)])),
  };
  const rubrics = RUBRIC_OPTIONS.filter(
    (r) => (r.value !== "watchlist" || can("view_ta")) && (r.value !== "techstack" || can("view_cve")),
  );
  const rubricItems: Record<string, string> = {
    [ALL]: "All rubrics",
    ...Object.fromEntries(rubrics.map((r) => [r.value, r.label])),
  };

  return (
    <div className="mb-6 flex flex-wrap items-center gap-3">
      <Input
        type="search"
        aria-label="Search articles"
        placeholder="Search title, source, CVE, actor…"
        value={searchText}
        onChange={(e) => onSearchText(e.target.value)}
        className="w-full text-xs sm:w-[420px]"
      />
      {/* `from` menang atas periode: tanpa pilihan aktif selama `from` terpasang. */}
      <SegmentedControl<NewsroomPeriod | "none">
        aria-label="Period"
        options={PERIOD_OPTIONS}
        value={ui.from ? "none" : ui.period}
        onChange={(v) => v !== "none" && onChange({ period: v })}
      />
      <Select
        items={countryItems}
        value={ui.country ?? ALL}
        onValueChange={(v) => onChange({ country: !v || v === ALL ? null : v })}
      >
        <SelectTrigger aria-label="Country" className="w-44 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL} className="text-xs">
            All countries
          </SelectItem>
          {codes.map((c) => (
            <SelectItem key={c} value={c} className="text-xs">
              {countryName(c)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        items={rubricItems}
        value={ui.rubric ?? ALL}
        onValueChange={(v) => onChange({ rubric: !v || v === ALL ? null : (v as RubricKey) })}
      >
        <SelectTrigger aria-label="Rubric" className="w-44 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL} className="text-xs">
            All rubrics
          </SelectItem>
          {rubrics.map((r) => (
            <SelectItem key={r.value} value={r.value} className="text-xs">
              {r.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <label className="flex items-center gap-2 text-xs text-foreground">
        <Checkbox checked={ui.incidentOnly} onCheckedChange={(v) => onChange({ incidentOnly: v === true })} />
        Incidents only
      </label>
      {ui.from && (
        <span className="inline-flex items-center gap-1 rounded-full bg-panel py-1 pr-1 pl-3 text-xs text-foreground">
          From {fmtShortDate(ui.from)}
          <button
            type="button"
            aria-label="Remove the From date"
            onClick={() => onChange({ from: null })}
            className="grid size-5 place-content-center rounded-full outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <X className="size-3" aria-hidden />
          </button>
        </span>
      )}
    </div>
  );
}
