import type { ExecFilters } from "@/lib/exec/filters";

const CVE_NOTE = "CVE figures cover all tracked CVEs and ignore the period filter.";

/** Catatan kaki kedua tampilan: apa yang sebenarnya dihitung angka di halaman, mengikuti dua kotak centang. */
export function ExecFootnote({ filters }: { filters: Pick<ExecFilters, "incidentOnly" | "confirmedOnly"> }) {
  const text = filters.confirmedOnly
    ? `Counts are LLM-confirmed incidents. ${CVE_NOTE}`
    : `Counts are ${filters.incidentOnly ? "threat news articles" : "all articles"}, not confirmed incidents; only Confirmed rate uses LLM-verified incidents. ${CVE_NOTE}`;
  return <p className="mt-8 text-2xs text-muted-foreground">{text}</p>;
}
