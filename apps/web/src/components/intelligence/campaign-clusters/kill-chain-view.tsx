import type { KillChain } from "@/lib/api/loose-types";
import { tint } from "@/lib/tint";

const LABEL_COLOR: Record<string, string> = { full_chain: "var(--severity-critical)", partial_chain: "var(--severity-high)", limited: "var(--muted-foreground)" };
const RISK_COLOR: Record<string, string> = { critical: "var(--severity-critical)", high: "var(--severity-high)", medium: "var(--severity-medium)", low: "var(--muted-foreground)" };

/** Port bagian Kill Chain di `_renderCampaignExpanded()` (`clusters.js:334-378`)
 * -- 12 fase MITRE kill-chain, segmen warna per-fase covered/enggak. */
export function KillChainView({ killChain: kc }: { killChain: KillChain }) {
  const labelColor = LABEL_COLOR[kc.completeness_label] ?? LABEL_COLOR.limited;
  const riskColor = RISK_COLOR[kc.operational_risk] ?? RISK_COLOR.low;
  const covered = kc.chain_visualization.filter((p) => p.covered && p.techniques.length > 0);

  return (
    <div className="mb-2.5">
      <div className="mb-1.5 flex flex-wrap items-center gap-2 text-sm font-semibold text-muted-foreground">
        Kill Chain Coverage
        <span className="rounded-full border px-1.5 py-0.5 text-xs font-bold normal-case" style={{ background: tint(labelColor, 13), borderColor: tint(labelColor, 33), color: labelColor }}>
          {kc.completeness_score}% — {kc.completeness_label.replace(/_/g, " ")}
        </span>
        <span className="text-xs normal-case" style={{ color: riskColor }}>
          Risk: {kc.operational_risk}
        </span>
      </div>
      <div className="mb-1.5 flex gap-0.5 px-0.5">
        {kc.chain_visualization.map((p) => (
          <div
            key={p.phase}
            title={`${p.phase.replace(/_/g, " ")}${p.techniques.length ? "\n" + p.techniques.join("\n") : ""}`}
            className="h-3 flex-1 rounded-full border"
            style={{ background: p.covered ? labelColor : tint("var(--muted-foreground)", 20), borderColor: p.covered ? labelColor : tint("var(--muted-foreground)", 30), opacity: p.covered ? 0.85 : 0.3 }}
          />
        ))}
      </div>
      <div className="mb-2 flex gap-0.5 px-0.5">
        {kc.chain_visualization.map((p) => (
          <div key={p.phase} title={p.phase.replace(/_/g, " ")} className="flex-1 truncate text-center font-mono text-[10px] text-muted-foreground">
            {p.phase.split("_")[0]}
          </div>
        ))}
      </div>
      {covered.length > 0 && (
        <div className="rounded-xl border border-border bg-background p-2">
          {covered.map((p) => (
            <div key={p.phase} className="flex items-start gap-1.5 py-0.5">
              <span className="w-[100px] flex-shrink-0 pt-px font-mono text-xs text-muted-foreground">{p.phase.replace(/_/g, " ")}</span>
              <div className="flex flex-wrap gap-1">
                {p.techniques.map((t, i) => (
                  <span key={i} className="rounded-full border border-tag-violet/30 bg-tag-violet/15 px-1 py-0.5 font-mono text-xs text-tag-violet">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
