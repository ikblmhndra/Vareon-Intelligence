import { EntityChip } from "@/components/entities/entity-chip";
import type { KillChain } from "@/lib/api/loose-types";
import { nameChip } from "@/lib/entities/name-chips";
import { cn } from "@/lib/utils";

/** Backend memberi 12 fase taktik ATT&CK (`KILL_CHAIN_PHASES`), mockup 2b menampilkan 7 ubin. Dua belas fase
 * dilipat jadi tujuh kelompok berurutan (bukan fase Lockheed Martin: fase "Recon" tak punya padanan di
 * taktik ATT&CK yang dipetakan backend, jadi ubinnya akan selalu kosong). Satu ubin = tercakup bila salah
 * satu fase anggotanya punya teknik. */
const GROUPS: { label: string; phases: string[] }[] = [
  { label: "Initial access", phases: ["initial_access"] },
  { label: "Execution", phases: ["execution"] },
  { label: "Persistence", phases: ["persistence", "privilege_escalation"] },
  { label: "Evasion", phases: ["defense_evasion", "credential_access"] },
  { label: "Discovery", phases: ["discovery", "lateral_movement"] },
  { label: "Collection", phases: ["collection", "exfiltration"] },
  { label: "C2 and impact", phases: ["command_and_control", "impact"] },
];

const phaseName = (p: string) => p.replace(/_/g, " ");

/** Kill chain campaign (spec 2b 6.10): judul "{label}, {n} of 7 phases", tujuh ubin "n TTP"/"none" (ubin
 * tercakup memakai tint destructive + `text-destructive-text`, tanpa mengubah warna teks), lalu daftar
 * teknik per fase yang tercakup (chip entity) seperti sebelum redesign. Label kelengkapan tetap dari
 * backend (dihitung atas 12 fase), jadi bisa sedikit tak selaras dengan "n of 7". */
export function KillChainView({ killChain: kc }: { killChain: KillChain }) {
  const byPhase = new Map(kc.chain_visualization.map((p) => [p.phase, p.techniques]));
  const tiles = GROUPS.map((g) => ({
    ...g,
    count: g.phases.reduce((n, p) => n + (byPhase.get(p)?.length ?? 0), 0),
  }));
  const covered = tiles.filter((t) => t.count > 0).length;
  const coveredPhases = kc.chain_visualization.filter((p) => p.covered && p.techniques.length > 0);

  return (
    <section aria-label="Kill chain">
      <h3 className="text-2xs font-semibold tracking-wide text-muted-foreground uppercase">
        Kill chain · {phaseName(kc.completeness_label)}, {covered} of {GROUPS.length} phases
      </h3>
      <ul className="mt-2 grid grid-cols-[repeat(auto-fit,minmax(4.5rem,1fr))] gap-1 lg:grid-cols-7">
        {tiles.map((t) => (
          <li
            key={t.label}
            title={t.phases.map(phaseName).join(", ")}
            className={cn(
              "rounded-md px-2 py-1.5 text-2xs",
              t.count > 0 ? "bg-destructive/15 text-destructive-text" : "bg-surface text-muted-foreground",
            )}
          >
            <p className="font-semibold break-words">{t.label}</p>
            <p className="mt-0.5">{t.count > 0 ? `${t.count} TTP` : "none"}</p>
          </li>
        ))}
      </ul>
      {coveredPhases.length > 0 && (
        <div className="mt-2 flex flex-col gap-1">
          {coveredPhases.map((p) => (
            <div key={p.phase} className="flex items-start gap-2">
              <span className="w-24 shrink-0 pt-0.5 text-2xs text-muted-foreground">{phaseName(p.phase)}</span>
              <div className="flex flex-wrap gap-1">
                {p.techniques.map((t, i) => (
                  <EntityChip key={i} {...nameChip("attack-pattern", t)} className="max-w-48" />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
