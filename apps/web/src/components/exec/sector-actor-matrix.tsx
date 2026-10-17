import type { ExecDashboardV2 } from "@/lib/api/loose-types";

function toTitleCase(s: string): string {
  return s.replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
}

/** Port matriks Sector × Actor Tier 2 (`exec.js:427-448`) -- heat merah,
 * gak ada drill-down (beda dari sector heatmap biru di atas). */
export function SectorActorMatrix({ d }: { d: ExecDashboardV2 }) {
  const sam = d.sector_actor_matrix;
  if (sam.sectors.length === 0) return null;
  const maxSam = sam.max_val || 1;

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr>
            <th />
            {sam.actors.map((a) => (
              <th key={a} className="max-w-[60px] px-1 py-1 font-mono break-words text-muted-foreground" title={a}>
                {toTitleCase(a).split(" ").slice(0, 2).join(" ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sam.sectors.map((sector, si) => (
            <tr key={sector}>
              <td className="max-w-[100px] px-2 py-1 font-mono whitespace-normal text-muted-foreground">
                {toTitleCase(sector)}
              </td>
              {sam.matrix[si].map((count, ai) => {
                const intensity = count / maxSam;
                return (
                  <td
                    key={ai}
                    className="px-1 py-1 text-center font-mono"
                    style={{
                      // Alfa maks 50%: di atasnya teks gelap maupun putih jatuh di bawah AA (4.0/4.39:1).
                      background: count > 0 ? `color-mix(in srgb, var(--severity-critical) ${Math.round(intensity * 45 + 5)}%, transparent)` : undefined,
                    }}
                    title={`${toTitleCase(sector)} × ${toTitleCase(sam.actors[ai])}: ${count}`}
                  >
                    {count || ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
