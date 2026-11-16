"use client";

import { useState } from "react";

import { EntityChip } from "@/components/entities/entity-chip";
import type { DiamondModel } from "@/lib/api/loose-types";
import { nameChips } from "@/lib/entities/name-chips";
import { tint } from "@/lib/tint";

const TACTIC_ORDER = [
  "initial_access",
  "execution",
  "persistence",
  "privilege_escalation",
  "defense_evasion",
  "credential_access",
  "discovery",
  "lateral_movement",
  "collection",
  "exfiltration",
  "command_and_control",
  "impact",
  "other",
];

/** Ringkasan satu baris tiap kuadran (spec 2b 6.10): jumlah, bukan daftar chip penuh; detail lengkap ada di
 * "expand". Bagian kosong dibuang, semua kosong = "—". */
const summarize = (parts: (string | null)[]) => parts.filter(Boolean).join(" · ") || "—";
const count = (n: number, word: string) => (n > 0 ? `${n} ${word}` : null);
function names(items: string[], limit: number): string | null {
  if (items.length === 0) return null;
  const rest = items.length - limit;
  return items.slice(0, limit).join(", ") + (rest > 0 ? ` +${rest}` : "");
}

function Quadrant({ label, color, children }: { label: string; color: string; children: string }) {
  return (
    <div className="rounded-md bg-surface px-3 py-2">
      <p className={`text-2xs font-semibold tracking-wide uppercase ${color}`}>{label}</p>
      <p className="mt-0.5 text-xs break-words text-foreground">{children}</p>
    </div>
  );
}

/** Diamond model (spec 2b 6.10): empat kuadran ringkas (Adversary, Infrastructure, Capability, Victim,
 * berisi hitungan seperti "4 IPs · 2 domains") + "expand" untuk detail penuh per-tactic MITRE
 * (port `_renderDiamondModel()`/`_dmFullDetails()`, `clusters.js:429-577`). Bentuk belah ketupat mockup
 * diganti grid 2x2 supaya muat di panel detail yang sempit. */
export function DiamondModelView({ model }: { model: DiamondModel }) {
  const [expanded, setExpanded] = useState(false);
  const adv = model.adversary;
  const inf = model.infrastructure;
  const cap = model.capability;
  const vic = model.victim;
  const meta = model.meta;

  const allTechs = Object.values(cap.attack_techniques).flat();
  const confColor = meta.confidence === "high" ? "var(--success)" : meta.confidence === "medium" ? "var(--severity-medium)" : "var(--muted-foreground)";

  return (
    <section aria-label="Diamond model">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-2xs font-semibold tracking-wide text-muted-foreground uppercase">Diamond model</h3>
        <span className="rounded-full border px-1.5 py-0.5 text-2xs" style={{ background: tint(confColor, 9), borderColor: tint(confColor, 27), color: confColor }}>
          conf: {meta.confidence}
        </span>
        <span className="rounded-full border border-border bg-surface px-1.5 py-0.5 text-2xs text-muted-foreground">{meta.direction}</span>
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((e) => !e)}
          className="ml-auto rounded-full border border-border px-2 py-0.5 text-2xs text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          {expanded ? "collapse" : "expand"}
        </button>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2">
        <Quadrant label="Adversary" color="text-warning-text">
          {summarize([names(adv.threat_actors, 2), adv.sophistication ? `Soph: ${adv.sophistication}` : null])}
        </Quadrant>
        <Quadrant label="Infrastructure" color="text-primary-text">
          {summarize([count(inf.ips.length, "IPs"), count(inf.domains.length, "domains"), count(inf.urls.length, "URLs")])}
        </Quadrant>
        <Quadrant label="Capability" color="text-tag-violet-text">
          {summarize([
            count(allTechs.length, "TTPs"),
            count(cap.malware.length + cap.tools.length, "malware/tools"),
            count(cap.cve_exploited.length, "CVEs"),
          ])}
        </Quadrant>
        <Quadrant label="Victim" color="text-success-text">
          {summarize([names(vic.industries, 2), names(vic.countries, 3)])}
        </Quadrant>
      </div>

      {expanded && (
        <div className="mt-2 grid grid-cols-2 gap-3 rounded-xl border border-border bg-background p-2">
          <div>
            <div className="mb-1.5 text-xs font-bold text-warning">Adversary</div>
            <FullSection title="Threat Actors" color="var(--severity-high)" items={adv.threat_actors} entity="intrusion-set" />
            <FullSection title="Actor Types" color="var(--severity-high)" items={adv.actor_types} />
            <FullSection title="Sponsoring Nations" color="var(--severity-high)" items={adv.sponsoring_nations} entity="location" />
            {adv.sophistication && (
              <div className="font-mono text-xs text-muted-foreground">
                Sophistication: <span className="text-warning">{adv.sophistication}</span>
              </div>
            )}
          </div>
          <div>
            <div className="mb-1.5 text-xs font-bold text-primary">Infrastructure</div>
            <FullSection title="Domains" color="var(--info)" items={inf.domains} />
            <FullSection title="IPs" color="var(--info)" items={inf.ips} />
            <FullSection title="URLs" color="var(--info)" items={inf.urls} />
          </div>
          <div>
            <div className="mb-1.5 text-xs font-bold text-tag-violet">Capability</div>
            {TACTIC_ORDER.map((tactic) => {
              const techs = cap.attack_techniques[tactic];
              if (!techs || techs.length === 0) return null;
              return <FullSection key={tactic} title={tactic.replace(/_/g, " ")} color="var(--tag-violet)" items={techs} entity="attack-pattern" />;
            })}
            <FullSection title="Malware" color="var(--tag-violet)" items={cap.malware} entity="malware,tool" />
            <FullSection title="Tools" color="var(--tag-violet)" items={cap.tools} entity="malware,tool" />
            <FullSection title="CVEs Exploited" color="var(--tag-violet)" items={cap.cve_exploited} entity="vulnerability" />
          </div>
          <div>
            <div className="mb-1.5 text-xs font-bold text-success">Victim</div>
            <FullSection title="Industries" color="var(--success)" items={vic.industries} entity="identity" />
            <FullSection title="Countries" color="var(--success)" items={vic.countries} entity="location" />
            <FullSection title="Org Types" color="var(--success)" items={vic.organization_types} />
          </div>
        </div>
      )}
    </section>
  );
}

function FullSection({ title, color, items, entity }: { title: string; color: string; items: string[]; entity?: string }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="mb-2">
      <div className="mb-1 text-sm font-semibold text-muted-foreground">{title}</div>
      <div className="flex flex-wrap gap-1">
        {items.map((v, i) =>
          entity ? (
            <EntityChip key={i} {...nameChips(entity, [v])[0]} className="max-w-40" />
          ) : (
            <span key={i} className="rounded-full border px-1.5 py-0.5 font-mono text-xs" style={{ background: tint(color, 9), borderColor: tint(color, 27), color }}>
              {v}
            </span>
          ),
        )}
      </div>
    </div>
  );
}
