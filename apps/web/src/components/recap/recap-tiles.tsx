import type { RecapDoc } from "@/lib/api/loose-types";
import { isoWeek } from "@/lib/recap/period";
import { signed } from "@/lib/recap/quality";
import { StatTile } from "@/components/ui/stat-tile";

const TILES: { key: string; label: string; pct: boolean }[] = [
  { key: "articles", label: "ARTICLES", pct: true },
  { key: "tweets", label: "POSTS", pct: true },
  { key: "iocs", label: "IOCs", pct: true },
  { key: "cves", label: "CVEs", pct: true },
  { key: "campaigns", label: "CAMPAIGNS", pct: false },
  { key: "new_threat_actors", label: "NEW ACTORS", pct: false },
];

/**
 * Enam angka utama recap. Selisih ke pekan lalu datang dari `quality.comparison` dan sengaja
 * netral (tanpa merah/hijau): lebih banyak aktivitas bukan berarti lebih buruk. Recap harian
 * tidak punya pembanding, jadi tanpa keterangan.
 */
export function RecapTiles({ doc }: { doc: RecapDoc }) {
  const counts = doc.counts ?? {};
  const comparison = doc.quality?.comparison;
  const prevWeek = comparison ? isoWeek(comparison.previous.period_start) : null;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {TILES.map(({ key, label, pct }) => {
        const c = comparison?.counts?.[key];
        let sub: string | undefined;
        if (c && prevWeek !== null) {
          sub =
            pct && c.delta_pct !== null
              ? `${signed(Math.round(c.delta_pct))}% vs week ${prevWeek}`
              : `${signed(c.delta)} vs week ${prevWeek}`;
        } else if (doc.kind === "weekly") {
          sub = "no prior week";
        }
        const value = (counts as Record<string, number | undefined>)[key] ?? 0;
        return (
          <StatTile
            key={key}
            label={label}
            value={<span className="font-code">{value.toLocaleString()}</span>}
            sub={sub}
          />
        );
      })}
    </div>
  );
}
