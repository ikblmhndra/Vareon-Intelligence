"use client";

import { useEffect, useMemo } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { EntityAttackTab } from "@/components/entities/entity-attack-tab";
import { EntityCvesTab } from "@/components/entities/entity-cves-tab";
import { EntityHeader } from "@/components/entities/entity-header";
import { EntityIndicatorsTab } from "@/components/entities/entity-indicators-tab";
import { EntityOverviewTab, useEntityTimeline } from "@/components/entities/entity-overview-tab";
import { EntityRelationshipsTab, useEntityRelationships } from "@/components/entities/entity-relationships-tab";
import { EntityStoriesTab } from "@/components/entities/entity-stories-tab";
import { EntityTimelineChart } from "@/components/entities/entity-timeline-chart";
import { HuntPanel } from "@/components/hunt/hunt-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { StatTile } from "@/components/ui/stat-tile";
import { TabPills, type TabPillItem } from "@/components/ui/tab-pills";
import { api } from "@/lib/api/client";
import { useCan } from "@/lib/auth/permissions";
import type { components } from "@/lib/api/schema";
import { ENTITY_TABS } from "@/lib/entities/types";
import { fmtAgo } from "@/lib/format";

type EntityDetail = components["schemas"]["EntityDetail"];

type TabKey = "overview" | "relationships" | "stories" | "indicators" | "cves" | "timeline" | "attack" | "hunt";

/** Tab ATT&CK hanya untuk tipe yang punya pemetaan teknik. */
const ATTACK_TYPES = new Set(["intrusion-set", "malware", "tool", "attack-pattern"]);

/** Tab Hunt (P7e): tipe yang bisa menjadi anchor hunting pack. */
const HUNT_TYPES = new Set(["intrusion-set", "malware", "tool", "campaign", "attack-pattern"]);

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
 * Cangkang halaman entity: ambil detail, redirect entity hasil merge, header + tile + tab. Isi tab
 * Relationships/Stories/Indicators/CVEs/ATT&CK dan menu Actions ada di komponen terpisah.
 */
export function EntityView({ id }: { id: number }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const can = useCan();

  const detail = useQuery({
    queryKey: ["entity", id],
    retry: false,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/entities/{entity_id}", {
        params: { path: { entity_id: id } },
      });
      if (data) return data;
      if (response.status === 404) return null;
      throw new Error(`entity gagal (${response.status})`, { cause: response.status });
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

  // Badge jumlah Relationships; kunci sama dengan tab/ringkasan, jadi satu request.
  const relationships = useEntityRelationships(id, entity != null && entity.merged_into_id == null);
  const relCount = relationships.data?.relationships.length;

  const mergedInto = entity?.merged_into_id ?? null;
  const tabParam = params.get("tab");
  useEffect(() => {
    if (mergedInto == null) return;
    const qs = tabParam ? `?${new URLSearchParams({ tab: tabParam })}` : "";
    router.replace(`/intelligence/entities/${mergedInto}${qs}`);
  }, [mergedInto, tabParam, router]);

  // Judul tab browser: layout segmen hanya tahu "Entities", jadi nama entity dipasang setelah dimuat.
  const entityName = entity?.name;
  useEffect(() => {
    if (!entityName) return;
    // Simpan judul sebelumnya dan pulihkan saat unmount/ganti nama: navigasi klien kembali ke daftar tidak
    // selalu memasang ulang metadata layout, jadi tab akan tetap menampilkan nama entity tanpa cleanup ini.
    const previous = document.title;
    const mine = `${entityName} · Entities`;
    document.title = mine;
    return () => {
      // halaman tujuan mungkin sudah memasang judulnya sendiri lebih dulu: jangan timpa dengan judul lama
      if (document.title === mine) document.title = previous;
    };
  }, [entityName]);

  const tabs = useMemo<TabPillItem<TabKey>[]>(() => {
    const items: TabPillItem<TabKey>[] = [
      { value: "overview", label: "Overview" },
      { value: "relationships", label: "Relationships", count: relCount },
      { value: "stories", label: "Stories", count: totals.data?.stories },
      { value: "indicators", label: "Indicators", count: totals.data?.indicators },
      { value: "cves", label: "CVEs", count: totals.data?.cves },
      { value: "timeline", label: "Timeline" },
    ];
    if (entity && ATTACK_TYPES.has(entity.type)) items.push({ value: "attack", label: "ATT&CK" });
    // pack berisi IOC: tab Hunt hanya untuk yang boleh melihat indikator
    if (entity && HUNT_TYPES.has(entity.type) && can("view_ioc")) items.push({ value: "hunt", label: "Hunt" });
    return items;
  }, [entity, relCount, totals.data, can]);

  if (detail.isPending || mergedInto != null) {
    return <StatePanel variant="loading" title="Loading entity" />;
  }
  if (detail.isError) {
    return detail.error instanceof Error && detail.error.cause === 403 ? (
      <StatePanel variant="no-access" title="You don't have access to entity pages." />
    ) : (
      <StatePanel variant="error" title="Could not load this entity. Try again later." />
    );
  }
  if (entity == null) {
    return (
      <StatePanel
        variant="empty"
        title="Entity not found"
        action={
          <Link href="/intelligence/entities" className="text-sm text-primary-text underline">
            Back to entities
          </Link>
        }
      />
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

  function setTab(next: TabKey) {
    const sp = new URLSearchParams(params.toString());
    if (next === "overview") sp.delete("tab");
    else sp.set("tab", next);
    const qs = sp.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  return (
    <div className="space-y-4">
      <EntityHeader entity={entity} listTabKey={listTab.key} />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatTile label="Mentions 30 days" value={entity.mentions_30d} />
        <StatTile label="Stories" value={totals.data?.stories ?? "-"} />
        <StatTile label="Indicators" value={totals.data?.indicators ?? "-"} />
        <StatTile label="CVEs" value={totals.data?.cves ?? "-"} />
        <StatTile label="Last seen" value={entity.last_seen ? fmtAgo(entity.last_seen) : "n/a"} />
      </div>
      <TabPills items={tabs} value={tab} onChange={setTab} aria-label="Entity sections" />
      <div role="tabpanel">
        {tab === "overview" && <EntityOverviewTab entity={entity} onViewAllRelationships={() => setTab("relationships")} />}
        {tab === "relationships" && <EntityRelationshipsTab entity={entity} />}
        {tab === "stories" && <EntityStoriesTab entity={entity} />}
        {tab === "indicators" && <EntityIndicatorsTab entity={entity} />}
        {tab === "cves" && <EntityCvesTab entity={entity} />}
        {tab === "timeline" && <TimelineTab entity={entity} />}
        {tab === "attack" && <EntityAttackTab entity={entity} />}
        {tab === "hunt" && <HuntPanel key={entity.id} anchorType="entity" anchorId={entity.id} />}
      </div>
    </div>
  );
}
