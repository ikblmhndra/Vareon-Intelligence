"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DomainBadges } from "@/components/intelligence/attack-db/domain-badges";
import type { AttackGroupDetail, AttackSoftwareDetail, AttackTechniqueDetail } from "@/lib/api/loose-types";

export type DetailTarget = { kind: "technique"; id: string } | { kind: "group"; id: string } | { kind: "software"; id: string } | null;

interface AttackDetailDialogProps {
  target: DetailTarget;
  onNavigate: (target: DetailTarget) => void;
  onClose: () => void;
}

function RefLink({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className="mr-2 mb-1 inline-block text-primary hover:underline">
      {children}
    </button>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="mb-1.5 text-sm font-semibold text-muted-foreground">{children}</div>;
}

/** Port `showTechniqueDetail()`/`showGroupDetail()`/`showSoftwareDetail()`
 * (`attack_db.js:367-469`) -- legacy pakai SATU overlay dibagi (`_openModal`),
 * 3 tipe entitas saling cross-link (technique->group/software dst).
 * Di sini disatuin jadi 1 dialog dengan state `DetailTarget`
 * (`kind`+`id`), `onNavigate` dipanggil pas klik cross-ref -> ganti
 * target -> query refetch, niru "isi ulang overlay yang sama" tanpa
 * nge-stack modal baru. */
export function AttackDetailDialog({ target, onNavigate, onClose }: AttackDetailDialogProps) {
  const techQuery = useQuery({
    queryKey: ["intelligence", "attack-technique", target?.kind === "technique" ? target.id : null],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/attack/techniques/{attack_id}", {
        params: { path: { attack_id: target!.id } },
      });
      if (error) throw error;
      return data as unknown as AttackTechniqueDetail;
    },
    enabled: target?.kind === "technique",
  });

  const groupQuery = useQuery({
    queryKey: ["intelligence", "attack-group", target?.kind === "group" ? target.id : null],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/attack/groups/{group_id}", { params: { path: { group_id: target!.id } } });
      if (error) throw error;
      return data as unknown as AttackGroupDetail;
    },
    enabled: target?.kind === "group",
  });

  const softwareQuery = useQuery({
    queryKey: ["intelligence", "attack-software", target?.kind === "software" ? target.id : null],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/attack/software/{software_id}", {
        params: { path: { software_id: target!.id } },
      });
      if (error) throw error;
      return data as unknown as AttackSoftwareDetail;
    },
    enabled: target?.kind === "software",
  });

  const isPending =
    (target?.kind === "technique" && techQuery.isPending) ||
    (target?.kind === "group" && groupQuery.isPending) ||
    (target?.kind === "software" && softwareQuery.isPending);
  const isError =
    (target?.kind === "technique" && techQuery.isError) ||
    (target?.kind === "group" && groupQuery.isError) ||
    (target?.kind === "software" && softwareQuery.isError);

  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] w-full max-w-xl overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="sr-only">ATT&amp;CK Detail</DialogTitle>
        </DialogHeader>

        {isPending && <p className="py-6 text-center text-xs text-muted-foreground">Loading…</p>}
        {isError && <p className="py-6 text-center text-xs text-destructive">Failed to load.</p>}

        {target?.kind === "technique" && techQuery.data && (
          <TechniqueDetail t={techQuery.data} onNavigate={onNavigate} />
        )}
        {target?.kind === "group" && groupQuery.data && <GroupDetail g={groupQuery.data} onNavigate={onNavigate} />}
        {target?.kind === "software" && softwareQuery.data && (
          <SoftwareDetail s={softwareQuery.data} onNavigate={onNavigate} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function TechniqueDetail({ t, onNavigate }: { t: AttackTechniqueDetail; onNavigate: (target: DetailTarget) => void }) {
  return (
    <div className="font-mono text-xs">
      <div className="mb-3 flex flex-wrap items-start gap-3">
        <div>
          <div className="text-[13px] text-primary">{t.attack_id}</div>
          <div className="mt-0.5 text-base font-bold text-foreground">{t.name}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {t.tactics.join(" · ")} <DomainBadges domains={t.domains} />
          </div>
        </div>
        <a href={t.url} target="_blank" rel="noopener noreferrer" className="ml-auto text-xs text-primary">
          MITRE ↗
        </a>
      </div>
      <div className="mb-3.5 max-h-44 overflow-y-auto text-[13px] leading-relaxed text-foreground">{t.description}</div>
      {t.platforms.length > 0 && <div className="mb-2.5 text-xs text-muted-foreground">Platforms: {t.platforms.join(", ")}</div>}
      {t.sub_techniques.length > 0 && (
        <div className="mb-3">
          <SectionLabel>Sub-techniques ({t.sub_techniques.length})</SectionLabel>
          {t.sub_techniques.map((s) => (
            <RefLink key={s.attack_id} onClick={() => onNavigate({ kind: "technique", id: s.attack_id })}>
              {s.attack_id} {s.name}
            </RefLink>
          ))}
        </div>
      )}
      <div className="mb-3">
        <SectionLabel>Mitigations ({t.mitigations.length})</SectionLabel>
        {t.mitigations.length === 0 ? (
          <span className="text-muted-foreground">None</span>
        ) : (
          t.mitigations.map((m) => (
            <div key={m.mitigation_id} className="mb-1.5">
              <span className="text-primary">{m.mitigation_id}</span> {m.name}
              <div className="text-xs text-muted-foreground">{m.description}</div>
            </div>
          ))
        )}
      </div>
      <div className="mb-3">
        <SectionLabel>Groups using this ({t.groups.length})</SectionLabel>
        {t.groups.length === 0 ? (
          <span className="text-muted-foreground">None</span>
        ) : (
          t.groups.map((g) => (
            <RefLink key={g.group_id} onClick={() => onNavigate({ kind: "group", id: g.group_id })}>
              {g.group_id} {g.name}
            </RefLink>
          ))
        )}
      </div>
      <div>
        <SectionLabel>Software ({t.software.length})</SectionLabel>
        {t.software.length === 0 ? (
          <span className="text-muted-foreground">None</span>
        ) : (
          t.software.map((s) => (
            <RefLink key={s.software_id} onClick={() => onNavigate({ kind: "software", id: s.software_id })}>
              {s.software_id} {s.name}
            </RefLink>
          ))
        )}
      </div>
    </div>
  );
}

function GroupDetail({ g, onNavigate }: { g: AttackGroupDetail; onNavigate: (target: DetailTarget) => void }) {
  return (
    <div className="font-mono text-xs">
      <div className="mb-3 flex flex-wrap items-start gap-3">
        <div>
          <div className="text-[13px] text-primary">{g.group_id}</div>
          <div className="mt-0.5 text-base font-bold text-foreground">{g.name}</div>
          {g.aliases.length > 0 && <div className="mt-0.5 text-xs text-muted-foreground">aka {g.aliases.slice(0, 5).join(", ")}</div>}
          <div className="mt-1">
            <DomainBadges domains={g.domains} />
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={() => openNavigatorForGroup(g.group_id)}>
            ⧉ Navigator
          </Button>
          <a href={g.url} target="_blank" rel="noopener noreferrer" className="text-xs text-primary">
            MITRE ↗
          </a>
        </div>
      </div>
      <div className="mb-3.5 max-h-40 overflow-y-auto text-[13px] leading-relaxed text-foreground">{g.description}</div>
      <div className="mb-3">
        <SectionLabel>Techniques used ({g.techniques.length})</SectionLabel>
        <div className="max-h-36 overflow-y-auto">
          {g.techniques.length === 0 ? (
            <span className="text-muted-foreground">None</span>
          ) : (
            g.techniques.map((t) => (
              <RefLink key={t.attack_id} onClick={() => onNavigate({ kind: "technique", id: t.attack_id })}>
                {t.attack_id}
              </RefLink>
            ))
          )}
        </div>
      </div>
      <div>
        <SectionLabel>Software ({g.software.length})</SectionLabel>
        {g.software.length === 0 ? (
          <span className="text-muted-foreground">None</span>
        ) : (
          g.software.map((s) => (
            <RefLink key={s.software_id} onClick={() => onNavigate({ kind: "software", id: s.software_id })}>
              {s.software_id} {s.name}
            </RefLink>
          ))
        )}
      </div>
    </div>
  );
}

function SoftwareDetail({ s, onNavigate }: { s: AttackSoftwareDetail; onNavigate: (target: DetailTarget) => void }) {
  return (
    <div className="font-mono text-xs">
      <div className="mb-3 flex flex-wrap items-start gap-3">
        <div>
          <div className="text-[13px] text-primary">{s.software_id}</div>
          <div className="mt-0.5 text-base font-bold text-foreground">{s.name}</div>
          <div className="mt-1 text-xs">
            <span
              className={`mr-1.5 rounded px-1.5 py-0.5 ${s.software_type === "malware" ? "bg-destructive/15 text-destructive-text" : "bg-primary/15 text-primary-text"}`}
            >
              {s.software_type}
            </span>
            <DomainBadges domains={s.domains} />
          </div>
        </div>
        <a href={s.url} target="_blank" rel="noopener noreferrer" className="ml-auto text-xs text-primary">
          MITRE ↗
        </a>
      </div>
      <div className="mb-3.5 max-h-40 overflow-y-auto text-[13px] leading-relaxed text-foreground">{s.description}</div>
      <div className="mb-3">
        <SectionLabel>Used by groups ({s.groups.length})</SectionLabel>
        {s.groups.length === 0 ? (
          <span className="text-muted-foreground">None</span>
        ) : (
          s.groups.map((g) => (
            <RefLink key={g.group_id} onClick={() => onNavigate({ kind: "group", id: g.group_id })}>
              {g.group_id} {g.name}
            </RefLink>
          ))
        )}
      </div>
      <div>
        <SectionLabel>Techniques ({s.techniques.length})</SectionLabel>
        <div className="max-h-32 overflow-y-auto">
          {s.techniques.length === 0 ? (
            <span className="text-muted-foreground">None</span>
          ) : (
            s.techniques.map((t) => (
              <RefLink key={t.attack_id} onClick={() => onNavigate({ kind: "technique", id: t.attack_id })}>
                {t.attack_id}
              </RefLink>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function openNavigatorForGroup(groupId: string) {
  const params = new URLSearchParams({ group_id: groupId });
  const layerUrl = encodeURIComponent(`${window.location.origin}/api/proxy/api/attack/navigator-layer?${params}`);
  window.open(`https://mitre-attack.github.io/attack-navigator/#layerURL=${layerUrl}`, "_blank");
}
