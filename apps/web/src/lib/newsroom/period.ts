import type { RubricKey } from "@/components/newsroom/rubric-queries";
import { periodStart, type NewsroomFilters } from "@/lib/newsroom/filters";

export type NewsroomPeriod = "1" | "7" | "30" | "all";

/** Empat periode Newsroom (spec 6.1). `days: null` = All; `words`/`suffix` dipakai kalimat ringkasan. */
export const NEWSROOM_PERIODS: readonly {
  key: NewsroomPeriod;
  label: string;
  days: number | null;
  words: string;
  suffix: string;
}[] = [
  { key: "1", label: "24h", days: 1, words: "24 hours", suffix: "in the last 24 hours" },
  { key: "7", label: "7d", days: 7, words: "7 days", suffix: "in the last 7 days" },
  { key: "30", label: "30d", days: 30, words: "30 days", suffix: "in the last 30 days" },
  { key: "all", label: "All", days: null, words: "all time", suffix: "of all time" },
];

/** `?period=`: selain "1" | "30" | "all" (termasuk tanpa parameter) = 7 hari, default Newsroom. */
export function parseNewsroomPeriod(value: string | null): NewsroomPeriod {
  return value === "1" || value === "30" || value === "all" ? value : "7";
}

export function newsroomPeriodInfo(key: NewsroomPeriod) {
  return NEWSROOM_PERIODS.find((p) => p.key === key) ?? NEWSROOM_PERIODS[1];
}

/** State UI Newsroom yang berasal dari URL/kontrol; `from` (?from=) menang atas `period`. */
export type NewsroomUi = {
  period: NewsroomPeriod;
  from: string | null;
  country: string | null;
  search: string;
  incidentOnly: boolean;
  rubric: RubricKey | null;
};

export function uiToFilters(ui: NewsroomUi): NewsroomFilters {
  return {
    search: ui.search,
    dateStart: ui.from ?? periodStart(newsroomPeriodInfo(ui.period).days ?? 0),
    dateEnd: "",
    country: ui.country,
    incidentOnly: ui.incidentOnly,
  };
}
