import { ChartCard } from "@/components/dashboard/stat-box";
import { GradedDoughnutChart, MultiLineChart, StackedBarChart } from "@/components/dashboard/charts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ShareBar, SHARE_BAR_SEGMENT } from "@/components/ui/share-bar";
import { execCountNoun, type ExecFilters } from "@/lib/exec/filters";
import { monthsCopy } from "@/lib/exec/heat";
import { toTitleCase } from "@/lib/exec/format";
import { cn } from "@/lib/utils";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

/** Lebih dari 6 tipe -> 5 teratas + "Other" (spec 6.2); sampai 6 tipe tampil apa adanya. */
function groupTypes(items: { name: string; count: number }[]): { name: string; count: number }[] {
  if (items.length <= 6) return items;
  const top = items.slice(0, 5);
  return [...top, { name: "Other", count: items.slice(5).reduce((a, b) => a + b.count, 0) }];
}

/** Kartu "News types": batang 100 % (`ShareBar`, pengganti doughnut) + legenda "{type} {n} · {pct}%", lalu
 * tren bulanan bertumpuk. Persentase dari jumlah breakdown, sama dengan pembulatan `ShareBar`. */
export function NewsTypesCard({
  d,
  filters,
  className,
}: {
  d: ExecDashboardV2;
  filters: Pick<ExecFilters, "incidentOnly" | "confirmedOnly">;
  className?: string;
}) {
  const grouped = groupTypes(d.news_type_breakdown);
  const total = grouped.reduce((a, b) => a + b.count, 0);
  const pct = (n: number) => (total > 0 ? Math.round((n / total) * 100) : 0);
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>News types</CardTitle>
        <CardDescription>
          Share of {d.total_incidents.toLocaleString()} {execCountNoun(filters)}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {grouped.length === 0 ? (
          <p className="py-4 text-xs text-muted-foreground">No news types in this period</p>
        ) : (
          <div className="space-y-3">
            <ShareBar
              aria-label="News types"
              items={grouped.map((g) => ({ label: toTitleCase(g.name), value: g.count }))}
            />
            <ul className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
              {grouped.map((g, i) => (
                <li key={g.name} className="flex items-center gap-2 text-xs">
                  <span
                    aria-hidden="true"
                    className={cn("size-2.5 shrink-0 rounded-[3px]", SHARE_BAR_SEGMENT[i % SHARE_BAR_SEGMENT.length])}
                  />
                  <span className="min-w-0 truncate">
                    {toTitleCase(g.name)} {g.count.toLocaleString()} · {pct(g.count)}%
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {d.newstype_trend.series.length > 0 && (
          <div>
            <p className="mb-2 text-2xs font-semibold tracking-wide text-muted-foreground uppercase">
              Monthly, last {monthsCopy(d.months.length)}
            </p>
            <div className="h-56">
              <StackedBarChart
                labels={d.newstype_trend.months}
                series={d.newstype_trend.series.map((s) => ({ label: toTitleCase(s.type), data: s.data }))}
              />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** "Sector trend" dan "Victim country trend": hanya 4 seri pertama supaya grafik terbaca; deret lengkap tetap
 * ada di CSV. */
export function SectorTrendCard({ d, className }: { d: ExecDashboardV2; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Sector trend</CardTitle>
        <CardDescription>Monthly articles, top 4 sectors</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="h-64">
          <MultiLineChart
            labels={d.months}
            series={d.sector_trend.slice(0, 4).map((s) => ({ label: toTitleCase(s.sector), data: s.data }))}
          />
        </div>
      </CardContent>
    </Card>
  );
}

export function VictimCountryTrendCard({ d, className }: { d: ExecDashboardV2; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Victim country trend</CardTitle>
        <CardDescription>Monthly articles naming a victim country</CardDescription>
      </CardHeader>
      <CardContent>
        {d.victim_country_trend.length > 0 ? (
          <div className="h-64">
            <MultiLineChart
              labels={d.months}
              series={d.victim_country_trend.slice(0, 4).map((c) => ({ label: toTitleCase(c.country), data: c.data }))}
            />
          </div>
        ) : (
          <p className="py-4 text-xs text-muted-foreground">No victim country data in this period</p>
        )}
      </CardContent>
    </Card>
  );
}

/** Sisa grafik lama yang dimiliki Task 17 ("More signals": Country trend + Source reliability spread). Tinggal
 * di sini, tidak berubah, sampai Task 17 memindahkannya supaya tidak ada grafik yang hilang. */
export function ExecLegacySignalCharts({ d }: { d: ExecDashboardV2 }) {
  const showSrSpread = d.view_config.sections.source_reliability_spread && Object.keys(d.source_reliability_spread).length > 0;
  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <ChartCard title="Country Trend" height={260}>
        <MultiLineChart
          labels={d.months}
          series={d.country_trend.map((c) => ({ label: toTitleCase(c.country), data: c.data }))}
        />
      </ChartCard>
      {showSrSpread && (
        <ChartCard title="Source Reliability Spread" height={260}>
          <GradedDoughnutChart counts={d.source_reliability_spread} />
        </ChartCard>
      )}
    </div>
  );
}
