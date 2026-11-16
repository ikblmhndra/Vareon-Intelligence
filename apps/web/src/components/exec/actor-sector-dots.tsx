import { EntityChip } from "@/components/entities/entity-chip";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { sectorAbbr, toTitleCase } from "@/lib/exec/format";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

const DOT_MAX = 20; // px, diameter titik terbesar
const DOT_MIN = 6; // px, supaya hitungan 1 dari max besar tetap terlihat

/** Matriks "Who targets which sector" (6.2, C12, D9). API mengirim sektor × aktor; di sini ditranspos (baris =
 * aktor) dan SEMUA baris/kolom yang dikirim ditampilkan. Diameter titik ∝ √(count/max); merah bila count ≥
 * ceil(0.75 × max_val), jadi ambang di catatan = titik merah terkecil. Titik `aria-hidden`; angka dibaca
 * pembaca layar lewat tabel sr-only (hanya sel non-nol). Tabel visual `role="presentation"` karena isinya
 * hanya tautan aktor + titik dekoratif. Overflow horizontal hanya di dalam kartu (lebar kolom tetap). */
export function ActorSectorDots({ matrix, className }: { matrix: ExecDashboardV2["sector_actor_matrix"]; className?: string }) {
  const { sectors, actors, max_val } = matrix;
  const max = max_val || 1;
  const threshold = Math.ceil(0.75 * max);
  const empty = sectors.length === 0 || actors.length === 0;

  const cells = actors.flatMap((actor, ai) =>
    sectors.map((sector, si) => ({ actor, sector, n: matrix.matrix[si]?.[ai] ?? 0 })),
  );

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Who targets which sector</CardTitle>
        <CardDescription>Articles linking each actor to a victim sector</CardDescription>
      </CardHeader>
      <CardContent>
        {empty ? (
          <p className="py-4 text-xs text-muted-foreground">No actor-sector links in this period</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table role="presentation" className="w-max table-fixed border-collapse text-xs">
                <colgroup>
                  <col className="w-36" />
                  {sectors.map((s) => (
                    <col key={s} className="w-14" />
                  ))}
                </colgroup>
                <thead>
                  <tr>
                    <th className="py-1" />
                    {sectors.map((s) => (
                      <th key={s} className="py-1 text-center text-2xs font-medium text-muted-foreground">
                        <abbr title={toTitleCase(s)} className="no-underline">
                          {sectorAbbr(s)}
                        </abbr>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {actors.map((actor, ai) => (
                    <tr key={actor}>
                      <td className="py-1 pr-2">
                        <EntityChip type="intrusion-set" name={actor} label={toTitleCase(actor)} className="max-w-32" />
                      </td>
                      {sectors.map((sector, si) => {
                        const n = matrix.matrix[si]?.[ai] ?? 0;
                        const size = Math.round(DOT_MIN + (DOT_MAX - DOT_MIN) * Math.sqrt(n / max));
                        return (
                          <td key={sector} className="h-7 text-center align-middle">
                            {n > 0 ? (
                              <span
                                aria-hidden="true"
                                title={`${toTitleCase(actor)} × ${toTitleCase(sector)}: ${n} articles`}
                                style={{ width: size, height: size }}
                                className={`inline-block rounded-full ${n >= threshold ? "bg-destructive" : "bg-foreground"}`}
                              />
                            ) : (
                              <span aria-hidden="true" className="text-muted-foreground">
                                ·
                              </span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-2xs text-muted-foreground">
              Dot size = article count. Red = {threshold} or more.
            </p>
            <table className="sr-only">
              <caption>Articles per actor and sector</caption>
              <thead>
                <tr>
                  <th>Actor</th>
                  <th>Sector</th>
                  <th>Articles</th>
                </tr>
              </thead>
              <tbody>
                {cells
                  .filter((c) => c.n > 0)
                  .map((c) => (
                    <tr key={`${c.actor}|${c.sector}`}>
                      <td>{toTitleCase(c.actor)}</td>
                      <td>{toTitleCase(c.sector)}</td>
                      <td>{c.n}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </>
        )}
      </CardContent>
    </Card>
  );
}
