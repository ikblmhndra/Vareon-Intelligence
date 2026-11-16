"use client";

import { Sparkles } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Markdown from "react-markdown";
import { toast } from "sonner";

import { EntityChip, type EntityChipItem } from "@/components/entities/entity-chip";
import { EntityRelationshipsSummary } from "@/components/entities/entity-relationships-tab";
import { EntityTimelineChart } from "@/components/entities/entity-timeline-chart";
import { MindmapWidget } from "@/components/mindmap/mindmap-widget";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";
import { fmtShortDate } from "@/lib/format";

type EntityDetail = components["schemas"]["EntityDetail"];

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {};
const str = (v: unknown): string => (typeof v === "string" ? v.trim() : "");
const strs = (v: unknown): string[] =>
  Array.isArray(v)
    ? [...new Set(v.map(str).filter((s) => s !== "" && s.toLowerCase() !== "unknown"))]
    : [];

/** Fragmen sitasi ATT&CK "(Citation: ...)" tidak berguna di UI dan dibuang dari deskripsi. */
const stripCitations = (s: string) =>
  s.replace(/\s*\(Citation:[^)]*\)/g, "").trim();

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

/** Deskripsi markdown entity (sitasi ATT&CK dibuang). */
function DescriptionBody({ text }: { text: string }) {
  return (
    <div className="prose prose-sm max-w-none text-sm">
      <Markdown
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {stripCitations(text)}
      </Markdown>
    </div>
  );
}

/**
 * Kartu kiri Overview (spec 2b 6.8, D24/D26). Actor: "AI profile" = ringkasan AI + tabel profil LLM + tombol
 * Generate/Regenerate + deskripsi yang bisa dilipat. Tipe lain: "About" berisi deskripsi saja. Profil yang dibuat
 * sebelum 0.8.16 belum punya `profile_summary`; analis diberi petunjuk untuk meregenerasi.
 */
function AboutCard({ entity }: { entity: EntityDetail }) {
  const can = useCan();
  const qc = useQueryClient();
  const isActor = entity.type === "intrusion-set";
  const canGenerate = isActor && can("manage_intel");
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
  const summary = entity.profile_summary?.trim() ?? "";
  const count = entity.profile_article_count;

  const title = isActor ? "AI profile" : "About";
  return (
    <section className="surface-raised space-y-3 rounded-xl p-5" aria-labelledby="entity-about">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <h2 id="entity-about" className="text-base font-semibold">
            {title}
          </h2>
          {hasProfile && entity.profile_generated_at && (
            <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>
                Generated {fmtShortDate(entity.profile_generated_at)}
                {count != null && ` from ${count} recent ${count === 1 ? "article" : "articles"}`}
              </span>
              <Chip kind="status" value="watch">
                REVIEW BEFORE SHARING
              </Chip>
            </p>
          )}
        </div>
        {canGenerate && (
          <Button variant="outline" size="sm" disabled={generate.isPending} onClick={() => generate.mutate()}>
            <Sparkles aria-hidden />
            {generate.isPending ? "Generating..." : hasProfile ? "Regenerate" : "Generate profile"}
          </Button>
        )}
      </div>
      {hasProfile && summary && (
        <div>
          <p className="text-2xs font-semibold tracking-wide text-muted-foreground uppercase">AI summary</p>
          <p className="mt-1 text-sm">{summary}</p>
        </div>
      )}
      {hasProfile && !summary && canGenerate && (
        <p className="text-xs text-muted-foreground">Regenerate to add a summary</p>
      )}
      {isActor && !hasProfile && <p className="text-sm text-muted-foreground">No AI profile yet.</p>}
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
              <Chips type="malware,tool" names={malware} />
            </Row>
          )}
          {tools.length > 0 && (
            <Row label="Tools">
              <Chips type="malware,tool" names={tools} />
            </Row>
          )}
        </dl>
      )}
      {isActor ? (
        entity.description && (
          <details className="group border-t border-border pt-3">
            <summary className="cursor-pointer rounded-sm text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background">
              Description
            </summary>
            <div className="mt-2">
              <DescriptionBody text={entity.description} />
            </div>
          </details>
        )
      ) : entity.description ? (
        <DescriptionBody text={entity.description} />
      ) : (
        <p className="text-sm text-muted-foreground">No description yet.</p>
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
  // Spec 2b 6.8: kiri = kartu profil/About; kanan = bulanan, ringkasan relasi, lalu mind map (actor).
  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      <div className="min-w-0 space-y-4">
        <AboutCard entity={entity} />
      </div>
      <div className="min-w-0 space-y-4">
        <section className="surface-raised space-y-3 rounded-xl p-5" aria-labelledby="entity-mentions">
          <h2 id="entity-mentions" className="text-base font-semibold">
            Mentions by month <span className="text-xs font-normal text-muted-foreground">last 12 months</span>
          </h2>
          {timeline.isPending ? (
            <Skeleton className="h-44 w-full" />
          ) : timeline.isError ? (
            <p role="alert" className="text-sm text-destructive">
              Could not load the timeline.
            </p>
          ) : (
            <EntityTimelineChart months={last12} highlightLast={2} />
          )}
        </section>
        <EntityRelationshipsSummary entity={entity} onViewAll={onViewAllRelationships} />
        {entity.type === "intrusion-set" && (
          <section className="surface-raised rounded-xl p-5" aria-label="Mind map">
            <MindmapWidget featureType="threat_actor" docId={entity.name} title={entity.name} />
          </section>
        )}
      </div>
    </div>
  );
}
