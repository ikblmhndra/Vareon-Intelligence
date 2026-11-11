"use client";

import { GradedDoughnutChart, MultiLineChart } from "@/components/dashboard/charts";
import { DashboardSectionLabel } from "@/components/dashboard/stat-box";
import { ClusterList } from "@/components/exec/role-gated-panels";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { toTitleCase } from "@/lib/exec/format";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

/** Baris "More signals" (D6): tiga kartu sinyal sekunder yang dulu tersebar. Kartu klaster dan spread
 * reliabilitas mengikuti gerbang `view_config.sections`; Country trend untuk semua peran, jadi baris ini selalu
 * ada. Semua seri `country_trend` digambar (tidak dipotong 4 seperti tren sektor/negara korban). */
export function MoreSignals({ d }: { d: ExecDashboardV2 }) {
  const { cluster_list: clusters, source_reliability_spread: sr } = d.view_config.sections;
  const showSr = sr && Object.keys(d.source_reliability_spread).length > 0;
  return (
    <section>
      <DashboardSectionLabel>More signals</DashboardSectionLabel>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {clusters && <ClusterList d={d} />}
        {showSr && (
          <Card>
            <CardHeader>
              <CardTitle>Source reliability spread</CardTitle>
              <CardDescription>Articles by source reliability grade</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="h-64">
                <GradedDoughnutChart counts={d.source_reliability_spread} />
              </div>
            </CardContent>
          </Card>
        )}
        <Card>
          <CardHeader>
            <CardTitle>Country trend</CardTitle>
            <CardDescription>Monthly articles per country</CardDescription>
          </CardHeader>
          <CardContent>
            {d.country_trend.length > 0 ? (
              <div className="h-64">
                <MultiLineChart
                  labels={d.months}
                  series={d.country_trend.map((c) => ({ label: toTitleCase(c.country), data: c.data }))}
                />
              </div>
            ) : (
              <p className="py-4 text-xs text-muted-foreground">No country data in this period</p>
            )}
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
