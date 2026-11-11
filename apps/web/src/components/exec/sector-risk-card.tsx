import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { MeterBar } from "@/components/ui/meter-bar";
import { Sparkline } from "@/components/ui/sparkline";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { EntityChip } from "@/components/entities/entity-chip";
import { fmtMonthYear } from "@/lib/format";
import { onTint, RISK_FORMULA_TITLE, sectorPeerBenchmark, toTitleCase } from "@/lib/exec/format";
import { cn } from "@/lib/utils";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

const FOCUS =
  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/** Kartu "Sector risk" (6.1). Semua baris yang dikembalikan API (maks. 8) tampil. Lebar kolom eksplisit +
 * `table-fixed`: tanpa lebar, kolom bisa runtuh jadi 0 (pelajaran 2b). `min-w` membuat tabel menggulir
 * mendatar di layar sempit, bukan memampatkan kolom. */
export function SectorRiskCard({ d, className }: { d: ExecDashboardV2; className?: string }) {
  const first = d.months[0];
  const last = d.months[d.months.length - 1];
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Sector risk</CardTitle>
        <CardDescription>Risk = volume (0–50) + trend (0–20) + spike (0–30), from monthly articles</CardDescription>
        <CardAction>
          <Tooltip>
            <TooltipTrigger
              type="button"
              className={cn("rounded-md text-xs font-medium text-primary-text outline-none hover:underline", FOCUS)}
            >
              How is risk scored?
            </TooltipTrigger>
            <TooltipContent className="whitespace-pre-line">{RISK_FORMULA_TITLE}</TooltipContent>
          </Tooltip>
        </CardAction>
      </CardHeader>
      <CardContent>
        {d.sector_risk_scores.length === 0 ? (
          <p className="py-4 text-xs text-muted-foreground">No sector risk data for this period</p>
        ) : (
          <Table className="min-w-[44rem] table-fixed">
            <colgroup>
              <col className="w-[22%]" />
              <col className="w-[24%]" />
              <col className="w-[10%]" />
              <col className="w-[16%]" />
              <col className="w-[13%]" />
              <col className="w-[15%]" />
            </colgroup>
            <TableHeader>
              <TableRow className="text-2xs text-muted-foreground uppercase">
                <TableHead>Sector</TableHead>
                <TableHead>Risk</TableHead>
                <TableHead>Articles</TableHead>
                <TableHead>Monthly trend</TableHead>
                <TableHead>Vs avg share</TableHead>
                <TableHead>Top TA</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {d.sector_risk_scores.map((sr) => {
                const series = d.sector_trend.find((s) => s.sector === sr.sector)?.data ?? [];
                const articles = series.reduce((a, b) => a + b, 0);
                const bench = sectorPeerBenchmark(d.sector_trend, sr.sector);
                return (
                  <TableRow key={sr.sector}>
                    <TableCell>
                      <EntityChip type="identity" name={sr.sector} label={toTitleCase(sr.sector)} />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <MeterBar
                          value={sr.risk_score}
                          max={100}
                          aria-label={`${toTitleCase(sr.sector)} risk score`}
                          className="min-w-0 flex-1"
                        />
                        <span className="font-code text-xs">{sr.risk_score}</span>
                        <Chip kind="risk" value={sr.risk_score} />
                      </div>
                    </TableCell>
                    <TableCell className="font-code text-xs">{articles.toLocaleString()}</TableCell>
                    <TableCell>
                      {series.length > 1 ? <Sparkline data={series} className="h-6 w-20" /> : <span className="text-xs">—</span>}
                    </TableCell>
                    <TableCell className={cn("font-code text-xs", onTint(bench.colorClass))}>{bench.text.replace(" vs avg", "")}</TableCell>
                    <TableCell className="text-xs">
                      {sr.top_actor ? (
                        <EntityChip type="intrusion-set" name={sr.top_actor} label={toTitleCase(sr.top_actor)} />
                      ) : (
                        "—"
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
        {/* Catatan penyebut: apa yang TIDAK ikut peringkat dan kenapa skor bisa tampak datar. */}
        <p className="mt-3 text-xs text-muted-foreground">
          {first && last && `Trend covers ${fmtMonthYear(`${first}-01`)} – ${fmtMonthYear(`${last}-01`)}. `}
          Articles tagged “General” ({d.sector_unspecified.toLocaleString()}) have no sector and are left out.
          {d.risk_volume_only && " Not enough monthly history yet, so risk uses volume only."}
        </p>
      </CardContent>
    </Card>
  );
}
