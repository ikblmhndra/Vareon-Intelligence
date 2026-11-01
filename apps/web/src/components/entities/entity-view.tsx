"use client";

import { useEffect, useMemo } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { EntityAttackTab } from "@/components/entities/entity-attack-tab";
import { EntityCvesTab } from "@/components/entities/entity-cves-tab";
import { EntityHero } from "@/components/entities/entity-hero";
import { EntityIndicatorsTab } from "@/components/entities/entity-indicators-tab";
import { EntityOverviewTab, useEntityTimeline } from "@/components/entities/entity-overview-tab";
import { EntityRelationshipsTab } from "@/components/entities/entity-relationships-tab";
import { EntityStoriesTab } from "@/components/entities/entity-stories-tab";
import { EntityTimelineChart } from "@/components/entities/entity-timeline-chart";
import { Skeleton } from "@/components/ui/skeleton";
import { TabPills, type TabPillItem } from "@/components/ui/tab-pills";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { ENTITY_TABS, entityTypeMeta } from "@/lib/entities/types";

type EntityDetail = components["schemas"]["EntityDetail"];

type TabKey = "overview" | "relationships" | "stories" | "indicators" | "cves" | "timeline" | "attack";

/** Tab ATT&CK hanya untuk tipe yang punya pemetaan teknik. */
const ATTACK_TYPES = new Set(["intrusion-set", "malware", "tool", "attack-pattern"]);

function TimelineTab({ entity }: { entity: EntityDetail }) {
  const timeline = useEntityTimeline(entity.id);
  return (
    <section className="surface-raised space-y-3 rounded-xl p-5" aria-labelledby="entity-timeline">
      <h2 id="entity-timeline" className="text-base font-semibold">
        Timeline <span className="text-xs font-normal text-muted-foreground">last 24 months</span>
      </h2>
      {timeline.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : timeline.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Could not load the timeline.
        </p>
      ) : (
        <EntityTimelineChart months={timeline.data} height={260} />
      )}
    </section>
  );
}

/**
 * Cangkang halaman entity: ambil detail, redirect entity hasil merge, hero + tab. Isi tab
 * Relationships/Stories/Indicators/CVEs/ATT&CK dan menu Actions ada di komponen terpisah.
 */
export function EntityView({ id }: { id: number }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const detail = useQuery({
    queryKey: ["entity", id],
    retry: false,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/entities/{entity_id}", {
        params: { path: { entity_id: id } },
      });
      if (data) return data;
      if (response.status === 404) return null;
      throw new Error(`entity gagal (${response.status})`);
    },
  });
  const entity = detail.data ?? null;

  // Total KPI dari sub-daftar dengan limit=1; hanya `total` yang dipakai.
  const totals = useQuery({
    queryKey: ["entity-totals", id],
    enabled: entity != null && entity.merged_into_id == null,
    queryFn: async () => {
      const path = { params: { path: { entity_id: id }, query: { limit: 1 } } };
      const [s, i, c] = await Promise.all([
        api.GET("/api/entities/{entity_id}/stories", path),
        api.GET("/api/entities/{entity_id}/indicators", path),
        api.GET("/api/entities/{entity_id}/cves", path),
      ]);
      return { stories: s.data?.total, indicators: i.data?.total, cves: c.data?.total };
    },
  });

  const mergedInto = entity?.merged_into_id ?? null;
  const tabParam = params.get("tab");
  useEffect(() => {
    if (mergedInto == null) return;
    const qs = tabParam ? `?${new URLSearchParams({ tab: tabParam })}` : "";
    router.replace(`/intelligence/entities/${mergedInto}${qs}`);
  }, [mergedInto, tabParam, router]);

  const tabs = useMemo<TabPillItem<TabKey>[]>(() => {
    const items: TabPillItem<TabKey>[] = [
      { value: "overview", label: "Overview" },
      { value: "relationships", label: "Relationships" },
      { value: "stories", label: "Stories" },
      { value: "indicators", label: "Indicators" },
      { value: "cves", label: "CVEs" },
      { value: "timeline", label: "Timeline" },
    ];
    if (entity && ATTACK_TYPES.has(entity.type)) items.push({ value: "attack", label: "ATT&CK" });
    return items;
  }, [entity]);

  if (detail.isPending || mergedInto != null) {
    return (
      <div className="space-y-3" role="status" aria-label="Loading entity">
        <Skeleton className="h-40 w-full rounded-3xl" />
        <Skeleton className="h-9 w-2/3" />
      </div>
    );
  }
  if (detail.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Could not load this entity. Try again later.
      </p>
    );
  }
  if (entity == null) {
    return (
      <section className="surface-raised space-y-3 rounded-xl p-5">
        <h2 className="text-base font-semibold">Entity not found</h2>
        <Link href="/intelligence/entities" className="text-sm text-primary-text underline">
          Back to entities
        </Link>
      </section>
    );
  }

  const requested = tabParam as TabKey | null;
  const tab: TabKey = tabs.some((t) => t.value === requested) ? (requested as TabKey) : "overview";
  const listTab =
    ENTITY_TABS.find(
      (t) =>
        t.types.includes(entity.type as never) &&
        (t.identityClass == null ||
          (entity.identity_class === "organization") === (t.identityClass === "organization")),
    ) ?? ENTITY_TABS[0];
  const meta = entityTypeMeta(entity.type, entity.identity_class);

  function setTab(next: TabKey) {
    const sp = new URLSearchParams(params.toString());
    if (next === "overview") sp.delete("tab");
    else sp.set("tab", next);
    const qs = sp.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  return (
    <div className="space-y-4">
      <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
        <Link href="/intelligence/entities" className="hover:text-foreground hover:underline">
          Entities
        </Link>
        <ChevronRight aria-hidden className="size-3" />
        <Link
          href={`/intelligence/entities?tab=${listTab.key}`}
          className="hover:text-foreground hover:underline"
        >
          {listTab.label}
        </Link>
        <ChevronRight aria-hidden className="size-3" />
        <span aria-current="page" className="text-foreground">
          {entity.name}
        </span>
        <span className="sr-only">{meta.label}</span>
      </nav>
      <EntityHero entity={entity} totals={totals.data ?? {}} />
      <TabPills items={tabs} value={tab} onChange={setTab} aria-label="Entity sections" />
      <div role="tabpanel">
        {tab === "overview" && <EntityOverviewTab entity={entity} />}
        {tab === "relationships" && <EntityRelationshipsTab entity={entity} />}
        {tab === "stories" && <EntityStoriesTab entity={entity} />}
        {tab === "indicators" && <EntityIndicatorsTab entity={entity} />}
        {tab === "cves" && <EntityCvesTab entity={entity} />}
        {tab === "timeline" && <TimelineTab entity={entity} />}
        {tab === "attack" && <EntityAttackTab entity={entity} />}
      </div>
    </div>
  );
}
