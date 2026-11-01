"use client";

import { Sparkles } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { EntityChip, type EntityChipItem } from "@/components/entities/entity-chip";
import { EntityRelationshipsSummary } from "@/components/entities/entity-relationships-tab";
import { EntityTimelineChart } from "@/components/entities/entity-timeline-chart";
import { MindmapWidget } from "@/components/mindmap/mindmap-widget";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";
import { relativeTime } from "@/lib/cve/freshness";

type EntityDetail = components["schemas"]["EntityDetail"];

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {};
const str = (v: unknown): string => (typeof v === "string" ? v.trim() : "");
const strs = (v: unknown): string[] =>
  Array.isArray(v)
    ? [...new Set(v.map(str).filter((s) => s !== "" && s.toLowerCase() !== "unknown"))]
    : [];

/** Query timeline dipakai bersama tab Overview (12 bulan) dan Timeline (24 bulan). */
export function useEntityTimeline(entityId: number) {
  return useQuery({
    queryKey: ["entity-timeline", entityId],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/entities/{entity_id}/timeline", {
        params: { path: { entity_id: entityId }, query: { months: 24 } },
      });
      if (error || !data) throw new Error("timeline failed");
      return data.months;
    },
  });
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="flex min-w-0 flex-wrap gap-1.5 text-sm">{children}</dd>
    </>
  );
}

function Chips({ type, names }: { type: string; names: string[] }) {
  // Nama dari profil LLM tidak punya entity di belakangnya: chip lewat resolve (W2).
  return (
    <>
      {[...new Set(names)].map((n) => (
        <EntityChip key={`${type}:${n}`} {...({ type, name: n } satisfies EntityChipItem)} />
      ))}
    </>
  );
}

/** Kartu About: deskripsi entity, dan untuk actor profil LLM tersimpan + tombol Generate/Regenerate. */
function AboutCard({ entity }: { entity: EntityDetail }) {
  const can = useCan();
  const qc = useQueryClient();
  const isActor = entity.type === "intrusion-set";
  const generate = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST("/api/entities/{entity_id}/profile", {
        params: { path: { entity_id: entity.id } },
      });
      if (error) throw new Error("profile failed");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["entity", entity.id] }),
    onError: () => toast.error("Could not generate the profile. Try again later."),
  });

  const p = obj(entity.profile);
  const hasProfile = isActor && Object.keys(p).length > 0;
  const identity = obj(p.identity);
  const motivation = obj(p.motivation);
  const targeting = obj(p.targeting_profile);
  const capability = obj(p.capability_assessment);
  const malware = Array.isArray(capability.known_malware)
    ? [...new Set(capability.known_malware.map((m) => str(obj(m).name)).filter(Boolean))]
    : [];
  const sponsor = str(identity.sponsoring_nation);
  const motive = str(motivation.primary_motivation);
  const actorType = str(identity.actor_type);
  const sectors = strs(targeting.targeted_sectors);
  const geos = strs(targeting.targeted_geographies);
  const tools = strs(capability.known_tools);

  return (
    <section className="surface-raised space-y-3 rounded-xl p-5" aria-labelledby="entity-about">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="entity-about" className="text-base font-semibold">
          About
        </h2>
        {isActor && can("manage_intel") && (
          <Button
            variant="outline"
            size="sm"
            className="max-sm:h-11"
            disabled={generate.isPending}
            onClick={() => generate.mutate()}
          >
            <Sparkles aria-hidden />
            {generate.isPending
              ? "Generating..."
              : hasProfile
                ? "Regenerate profile"
                : "Generate profile"}
          </Button>
        )}
      </div>
      {entity.description ? (
        <p className="text-sm whitespace-pre-line">{entity.description}</p>
      ) : (
        !hasProfile && <p className="text-sm text-muted-foreground">No description yet.</p>
      )}
      {hasProfile && (
        <dl className="grid grid-cols-[8rem_1fr] items-baseline gap-x-3 gap-y-2.5 max-sm:grid-cols-1 max-sm:gap-y-1">
          {actorType && <Row label="Actor type">{actorType}</Row>}
          {motive && <Row label="Motivation">{motive}</Row>}
          {sponsor && sponsor.toLowerCase() !== "null" && (
            <Row label="Sponsor">
              <Chips type="location" names={[sponsor]} />
            </Row>
          )}
          {sectors.length > 0 && (
            <Row label="Targets: sectors">
              <Chips type="identity" names={sectors} />
            </Row>
          )}
          {geos.length > 0 && (
            <Row label="Targets: geographies">
              <Chips type="location" names={geos} />
            </Row>
          )}
          {malware.length > 0 && (
            <Row label="Malware">
              <Chips type="malware" names={malware} />
            </Row>
          )}
          {tools.length > 0 && (
            <Row label="Tools">
              <Chips type="tool" names={tools} />
            </Row>
          )}
        </dl>
      )}
      {hasProfile && (
        <p className="flex flex-wrap justify-between gap-2 border-t border-border pt-2 text-xs text-muted-foreground">
          <span>
            <Sparkles aria-hidden className="mr-1 inline size-3" />
            Profile written by the LLM
            {entity.profile_generated_at && ` · ${relativeTime(entity.profile_generated_at)}`}
          </span>
          <span>Review before sharing</span>
        </p>
      )}
    </section>
  );
}

export function EntityOverviewTab({
  entity,
  onViewAllRelationships,
}: {
  entity: EntityDetail;
  onViewAllRelationships: () => void;
}) {
  const timeline = useEntityTimeline(entity.id);
  const last12 = timeline.data?.slice(-12) ?? [];
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="min-w-0 space-y-4">
        <AboutCard entity={entity} />
        <section
          className="surface-raised space-y-3 rounded-xl p-5"
          aria-labelledby="entity-mentions"
        >
          <h2 id="entity-mentions" className="text-base font-semibold">
            Mentions per month{" "}
            <span className="text-xs font-normal text-muted-foreground">last 12 months</span>
          </h2>
          {timeline.isPending ? (
            <Skeleton className="h-44 w-full" />
          ) : timeline.isError ? (
            <p role="alert" className="text-sm text-destructive">
              Could not load the timeline.
            </p>
          ) : (
            <EntityTimelineChart months={last12} />
          )}
        </section>
        {entity.type === "intrusion-set" && (
          <MindmapWidget featureType="threat_actor" docId={entity.name} title={entity.name} />
        )}
      </div>
      <EntityRelationshipsSummary entity={entity} onViewAll={onViewAllRelationships} />
    </div>
  );
}
