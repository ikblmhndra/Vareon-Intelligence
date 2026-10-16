"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { TAActivityTimelineChart } from "@/components/dashboard/charts";
import { MindmapWidget } from "@/components/mindmap/mindmap-widget";
import type { TaExploitedVuln, TaKnownMalware, TaProfile, TaProfileResponse, TaTimeline } from "@/lib/api/loose-types";

const DORMANCY_STYLE: Record<string, { icon: string; color: string }> = {
  ACTIVE: { icon: "●", color: "text-success" },
  DORMANT: { icon: "●", color: "text-warning" },
  RESURGENT: { icon: "●", color: "text-destructive" },
};

function Tag({ children }: { children: React.ReactNode }) {
  return <span className="mr-1.5 mb-1 inline-block rounded-full border border-border bg-background px-1.5 py-0.5 font-mono text-xs text-foreground">{children}</span>;
}

function Val({ v }: { v: string | null | undefined }) {
  return v ? <span className="text-foreground">{v}</span> : <span className="text-muted-foreground">—</span>;
}

function Kv({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-0.5 text-sm font-semibold text-muted-foreground">{label}</div>
      <div className="text-xs">{children}</div>
    </div>
  );
}

function TagList({ items }: { items: string[] | undefined }) {
  if (!items || items.length === 0) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <div className="mt-1">
      {items.map((v, i) => (
        <Tag key={i}>{v}</Tag>
      ))}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-b border-border pb-4 last:border-none">
      <div className="mb-2 text-sm font-semibold text-primary">{title}</div>
      {children}
    </div>
  );
}

/** Port `taShowProfileModal()`+`_renderProfileBody()`+`_tapLoadTimeline()`
 * (`ta.js:655-1006`) -- profil TA terstruktur (10 section) + activity
 * timeline (Chart.js, dormancy state) + regenerate + Mind Map (pakai
 * `MindmapWidget` Grup G5 -- legacy cuma toggle-only di sini, edit
 * dibiarin ada juga biar satu komponen konsisten, bukan hand-roll
 * toggle terpisah lagi). */
export function TaProfileDialog({ actorName, onClose }: { actorName: string | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [regenerating, setRegenerating] = useState(false);

  const profileQuery = useQuery({
    queryKey: ["ta-room", "ta-profile", actorName],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/ta/profile/{name}", { params: { path: { name: actorName! } } });
      if (error) throw error;
      return data as unknown as TaProfileResponse;
    },
    enabled: actorName !== null,
  });

  const timelineQuery = useQuery({
    queryKey: ["ta-room", "ta-timeline", actorName],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/ta/{actor}/timeline", {
        params: { path: { actor: actorName! }, query: { months: 24 } },
      });
      if (error) throw error;
      return data as unknown as TaTimeline;
    },
    enabled: actorName !== null,
  });

  async function regenerate() {
    if (!actorName) return;
    setRegenerating(true);
    try {
      const { error } = await api.POST("/api/ta/profile/generate", { body: { name: actorName } });
      if (error) throw new Error(JSON.stringify(error));
      toast.success(`Profile regenerated for "${actorName}".`);
      await queryClient.invalidateQueries({ queryKey: ["ta-room", "ta-profile", actorName] });
      await queryClient.invalidateQueries({ queryKey: ["ta-room", "ta-watchlist"] });
    } catch (e) {
      toast.error(`Regeneration failed: ${(e as Error).message}`);
    } finally {
      setRegenerating(false);
    }
  }

  const profile = profileQuery.data?.profile;
  const tl = timelineQuery.data;
  const dormancy = tl ? (DORMANCY_STYLE[tl.dormancy_state] ?? DORMANCY_STYLE.DORMANT) : null;

  return (
    <Dialog open={actorName !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] w-full max-w-3xl overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <div className="flex flex-wrap items-center gap-2">
            <DialogTitle className="font-mono text-sm">{actorName}</DialogTitle>
            <Button size="sm" variant="outline" className="ml-auto h-6 px-2 text-xs" disabled={regenerating} onClick={() => void regenerate()}>
              {regenerating ? "Regenerating…" : "Regenerate"}
            </Button>
          </div>
          {profile && <MetaChips profile={profile} />}
        </DialogHeader>

        {profileQuery.isPending && <p className="py-8 text-center text-xs text-muted-foreground">Loading…</p>}
        {profileQuery.isError && <p className="py-8 text-center text-xs text-destructive">Failed to load profile.</p>}
        {profileQuery.data && !profileQuery.data.exists && (
          <p className="py-8 text-center text-xs text-muted-foreground">No profile found — generate one first.</p>
        )}

        {profile && actorName && (
          <div className="space-y-4 py-1">
            <div>
              <MindmapWidget featureType="threat_actor" docId={actorName} title={actorName} />
            </div>

            <Section title={`Activity Timeline ${dormancy ? `— ${dormancy.icon} ${tl!.dormancy_state}` : ""}`}>
              {timelineQuery.isPending && <p className="text-xs text-muted-foreground">Loading timeline…</p>}
              {timelineQuery.isError && <p className="text-xs text-destructive">Failed to load timeline.</p>}
              {tl && (
                <>
                  <div className="relative h-40">
                    <TAActivityTimelineChart labels={tl.months} articleCounts={tl.article_counts} tweetCounts={tl.tweet_counts} ransomCounts={tl.ransom_counts} />
                  </div>
                  <div className="mt-2 font-mono text-xs leading-loose text-muted-foreground">
                    {tl.state_transitions.length === 0 ? (
                      <span>No state transitions in 24-month window</span>
                    ) : (
                      tl.state_transitions.map((t, i) => (
                        <span key={i} className="mr-4">
                          ⟶ {t.month}: <span className="text-foreground">{t.from}</span> → <span className="text-warning">{t.to}</span>
                        </span>
                      ))
                    )}
                  </div>
                </>
              )}
            </Section>

            <ProfileBody profile={profile} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function MetaChips({ profile }: { profile: TaProfile }) {
  const id = profile.identity ?? {};
  const meta = profile.profile_metadata ?? {};
  const conf = meta.analyst_confidence || "unknown";
  const tlp = meta.tlp_marking || "";
  return (
    <div className="flex flex-wrap gap-1.5 pt-1">
      {id.actor_type && <Tag>{id.actor_type.toUpperCase()}</Tag>}
      {id.active_status && <Tag>{id.active_status}</Tag>}
      {conf !== "unknown" && <Tag>CONFIDENCE: {conf.toUpperCase()}</Tag>}
      {tlp && <Tag>{tlp}</Tag>}
      {id.sponsoring_nation && <Tag>🏴 {id.sponsoring_nation}</Tag>}
    </div>
  );
}

function MalwareTable({ items }: { items: TaKnownMalware[] | undefined }) {
  if (!items || items.length === 0) return <span className="text-xs text-muted-foreground">None documented</span>;
  return (
    <table className="w-full border-collapse text-xs">
      <thead>
        <tr className="border-b border-border text-left text-xs text-muted-foreground uppercase">
          <th className="py-1 pr-2">Name</th>
          <th className="py-1 pr-2">Type</th>
          <th className="py-1">Notes</th>
        </tr>
      </thead>
      <tbody>
        {items.map((m, i) => (
          <tr key={i} className="border-b border-border last:border-none">
            <td className="py-1 pr-2 font-semibold text-primary">{m.name || "—"}</td>
            <td className="py-1 pr-2">
              <Tag>{m.type || "—"}</Tag>
            </td>
            <td className="py-1 text-muted-foreground">{m.notes || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function VulnsTable({ items }: { items: TaExploitedVuln[] | undefined }) {
  if (!items || items.length === 0) return <span className="text-xs text-muted-foreground">None documented</span>;
  return (
    <table className="w-full border-collapse text-xs">
      <thead>
        <tr className="border-b border-border text-left text-xs text-muted-foreground uppercase">
          <th className="py-1 pr-2">CVE</th>
          <th className="py-1 pr-2">Product</th>
          <th className="py-1">Notes</th>
        </tr>
      </thead>
      <tbody>
        {items.map((v, i) => (
          <tr key={i} className="border-b border-border last:border-none">
            <td className="py-1 pr-2 font-code text-warning">{v.cve_id || "—"}</td>
            <td className="py-1 pr-2">{v.product || "—"}</td>
            <td className="py-1 text-muted-foreground">{v.notes || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ProfileBody({ profile: p }: { profile: TaProfile }) {
  const id = p.identity ?? {};
  const mot = p.motivation ?? {};
  const tgt = p.targeting_profile ?? {};
  const cap = p.capability_assessment ?? {};
  const inf = p.infrastructure ?? {};
  const det = p.detection_and_defense ?? {};
  const rel = p.organizational_relevance ?? {};
  const gaps = p.intelligence_gaps ?? [];
  const refs = p.references ?? [];
  const camps = p.campaign_history ?? [];
  const ttpPhases = Object.entries(cap.attack_techniques ?? {}).filter(([, v]) => v && v.length > 0);
  const iocs = inf.known_iocs ?? {};
  const hasIocs = (iocs.ips?.length || 0) + (iocs.domains?.length || 0) + (iocs.hashes?.length || 0) + (iocs.urls?.length || 0) > 0;

  return (
    <>
      <Section title="Identity">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kv label="Primary Name">
            <Val v={id.primary_name} />
          </Kv>
          <Kv label="Actor Type">
            <Val v={id.actor_type} />
          </Kv>
          <Kv label="Sponsoring Nation">
            <Val v={id.sponsoring_nation} />
          </Kv>
          <Kv label="Affiliated Group">
            <Val v={id.affiliated_group} />
          </Kv>
          <Kv label="First Observed">
            <Val v={id.first_observed} />
          </Kv>
          <Kv label="Last Active">
            <Val v={id.last_active} />
          </Kv>
          <Kv label="Active Status">
            <Val v={id.active_status} />
          </Kv>
          <Kv label="MITRE ID">
            <Val v={id.tracking_ids?.mitre_group_id} />
          </Kv>
        </div>
        {(id.tracking_ids?.other_ids?.length ?? 0) > 0 && (
          <div className="mt-2">
            <Kv label="Other IDs">
              <TagList items={id.tracking_ids?.other_ids} />
            </Kv>
          </div>
        )}
        {(id.aliases?.length ?? 0) > 0 && (
          <div className="mt-2">
            <Kv label="Aliases">
              <TagList items={id.aliases} />
            </Kv>
          </div>
        )}
      </Section>

      <Section title="Motivation">
        <div className="grid grid-cols-2 gap-3">
          <Kv label="Primary">
            <Val v={mot.primary_motivation} />
          </Kv>
          <Kv label="Approach">
            <Val v={mot.targeting_approach} />
          </Kv>
        </div>
        {(mot.secondary_motivations?.length ?? 0) > 0 && (
          <div className="mt-2">
            <Kv label="Secondary">
              <TagList items={mot.secondary_motivations} />
            </Kv>
          </div>
        )}
        {(mot.strategic_objectives?.length ?? 0) > 0 && (
          <div className="mt-2">
            <Kv label="Objectives">
              <TagList items={mot.strategic_objectives} />
            </Kv>
          </div>
        )}
      </Section>

      <Section title="Targeting Profile">
        <div className="grid grid-cols-2 gap-3">
          <Kv label="Sectors">
            <TagList items={tgt.targeted_sectors} />
          </Kv>
          <Kv label="Geographies">
            <TagList items={tgt.targeted_geographies} />
          </Kv>
          <Kv label="Org Types">
            <TagList items={tgt.targeted_organization_types} />
          </Kv>
          <Kv label="High-Value Assets">
            <TagList items={tgt.high_value_assets_targeted} />
          </Kv>
        </div>
      </Section>

      <Section title="Capability Assessment">
        <div className="mb-3 grid grid-cols-2 gap-3">
          <Kv label="Sophistication">
            <Val v={cap.sophistication_level} />
          </Kv>
          <Kv label="Dev Capability">
            <Val v={cap.development_capability} />
          </Kv>
        </div>
        <div className="mb-3">
          <Kv label="Known Tools">
            <TagList items={cap.known_tools} />
          </Kv>
        </div>
        <div className="mb-3">
          <div className="mb-1 text-sm font-semibold text-muted-foreground">Malware</div>
          <MalwareTable items={cap.known_malware} />
        </div>
        <div className="mb-3">
          <div className="mb-1 text-sm font-semibold text-muted-foreground">Exploited Vulnerabilities</div>
          <VulnsTable items={cap.exploited_vulnerabilities} />
        </div>
        <div>
          <div className="mb-1 text-sm font-semibold text-muted-foreground">Attack Techniques (MITRE)</div>
          {ttpPhases.length === 0 ? (
            <span className="text-xs text-muted-foreground">None documented</span>
          ) : (
            ttpPhases.map(([phase, techs]) => (
              <div key={phase} className="mb-1.5">
                <Kv label={phase.replace(/_/g, " ")}>
                  <TagList items={techs} />
                </Kv>
              </div>
            ))
          )}
        </div>
      </Section>

      <Section title="Infrastructure">
        <div className="mb-3 grid grid-cols-2 gap-3">
          <Kv label="Infrastructure Reuse">
            <Val v={inf.infrastructure_reuse} />
          </Kv>
          <Kv label="Notes">
            <Val v={inf.infrastructure_notes} />
          </Kv>
        </div>
        {(inf.c2_patterns?.length ?? 0) > 0 && (
          <div className="mb-2">
            <Kv label="C2 Patterns">
              <TagList items={inf.c2_patterns} />
            </Kv>
          </div>
        )}
        {(inf.hosting_preferences?.length ?? 0) > 0 && (
          <div className="mb-2">
            <Kv label="Hosting">
              <TagList items={inf.hosting_preferences} />
            </Kv>
          </div>
        )}
        <div>
          <div className="mb-1 text-sm font-semibold text-muted-foreground">IOCs</div>
          {!hasIocs ? (
            <span className="text-xs text-muted-foreground">None documented</span>
          ) : (
            <div className="flex flex-col gap-2">
              {(iocs.ips?.length ?? 0) > 0 && (
                <Kv label="IPs">
                  <TagList items={iocs.ips} />
                </Kv>
              )}
              {(iocs.domains?.length ?? 0) > 0 && (
                <Kv label="Domains">
                  <TagList items={iocs.domains} />
                </Kv>
              )}
              {(iocs.hashes?.length ?? 0) > 0 && (
                <Kv label="Hashes">
                  <TagList items={iocs.hashes} />
                </Kv>
              )}
              {(iocs.urls?.length ?? 0) > 0 && (
                <Kv label="URLs">
                  <TagList items={iocs.urls} />
                </Kv>
              )}
            </div>
          )}
        </div>
      </Section>

      <Section title="Campaign History">
        {camps.length === 0 ? (
          <span className="text-xs text-muted-foreground">None documented</span>
        ) : (
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground uppercase">
                <th className="py-1 pr-2">Campaign</th>
                <th className="py-1 pr-2">Date Range</th>
                <th className="py-1 pr-2">Sectors</th>
                <th className="py-1">Source</th>
              </tr>
            </thead>
            <tbody>
              {camps.map((c, i) => (
                <tr key={i} className="border-b border-border last:border-none">
                  <td className="py-1 pr-2 font-semibold text-foreground">{c.campaign_name || "—"}</td>
                  <td className="py-1 pr-2 font-mono text-xs whitespace-nowrap">{c.date_range || "—"}</td>
                  <td className="py-1 pr-2">
                    <TagList items={c.targeted_sectors} />
                  </td>
                  <td className="py-1 text-xs text-muted-foreground">{c.source_reference || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Detection & Defense">
        <div className="mb-3">
          <div className="mb-1 text-sm font-semibold text-muted-foreground">Detection Opportunities</div>
          {(det.detection_opportunities?.length ?? 0) === 0 ? (
            <span className="text-xs text-muted-foreground">None documented</span>
          ) : (
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground uppercase">
                  <th className="py-1 pr-2">Layer</th>
                  <th className="py-1 pr-2">Description</th>
                  <th className="py-1">MITRE Ref</th>
                </tr>
              </thead>
              <tbody>
                {det.detection_opportunities!.map((o, i) => (
                  <tr key={i} className="border-b border-border last:border-none">
                    <td className="py-1 pr-2">
                      <Tag>{o.layer || "—"}</Tag>
                    </td>
                    <td className="py-1 pr-2">{o.description || "—"}</td>
                    <td className="py-1 font-mono text-xs text-warning">{o.mitre_technique_ref || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div>
          <div className="mb-1 text-sm font-semibold text-muted-foreground">Recommended Mitigations</div>
          {(det.recommended_mitigations?.length ?? 0) === 0 ? (
            <span className="text-xs text-muted-foreground">None documented</span>
          ) : (
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground uppercase">
                  <th className="py-1 pr-2">Mitigation</th>
                  <th className="py-1 pr-2">ID</th>
                  <th className="py-1">Priority</th>
                </tr>
              </thead>
              <tbody>
                {det.recommended_mitigations!.map((m, i) => (
                  <tr key={i} className="border-b border-border last:border-none">
                    <td className="py-1 pr-2">{m.mitigation || "—"}</td>
                    <td className="py-1 pr-2 font-mono text-xs text-primary">{m.mitre_mitigation_id || "—"}</td>
                    <td
                      className={
                        "py-1 text-xs " +
                        (m.priority === "immediate" ? "text-destructive" : m.priority === "short-term" ? "text-warning" : "text-muted-foreground")
                      }
                    >
                      {m.priority || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Section>

      <Section title="Organizational Relevance">
        <div className="mb-3 grid grid-cols-2 gap-3">
          <Kv label="Sector Relevance">
            <Val v={rel.sector_relevance} />
          </Kv>
          <Kv label="Monitoring Priority">
            <Val v={rel.monitoring_priority} />
          </Kv>
        </div>
        {rel.relevance_rationale && (
          <div className="mb-2">
            <Kv label="Rationale">
              <p className="mt-1 text-xs leading-relaxed text-foreground">{rel.relevance_rationale}</p>
            </Kv>
          </div>
        )}
        {(rel.recommended_actions?.length ?? 0) > 0 && (
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground uppercase">
                <th className="py-1 pr-2">Timeframe</th>
                <th className="py-1">Action</th>
              </tr>
            </thead>
            <tbody>
              {rel.recommended_actions!.map((a, i) => (
                <tr key={i} className="border-b border-border last:border-none">
                  <td className="py-1 pr-2 font-mono text-xs whitespace-nowrap text-warning">{a.timeframe || "—"}</td>
                  <td className="py-1">{a.action || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {gaps.length > 0 && (
        <Section title="Intelligence Gaps">
          <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            {gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </Section>
      )}

      {refs.length > 0 && (
        <Section title="References">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground uppercase">
                <th className="py-1 pr-2">Title</th>
                <th className="py-1 pr-2">Source</th>
                <th className="py-1">Date</th>
              </tr>
            </thead>
            <tbody>
              {refs.map((r, i) => (
                <tr key={i} className="border-b border-border last:border-none">
                  <td className="py-1 pr-2">
                    {r.url ? (
                      <a href={r.url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                        {r.title || r.url}
                      </a>
                    ) : (
                      r.title || "—"
                    )}
                  </td>
                  <td className="py-1 pr-2 text-muted-foreground">{r.source || "—"}</td>
                  <td className="py-1 font-mono text-xs whitespace-nowrap">{r.date || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
    </>
  );
}
