"use client";

import { EyeIcon, XIcon } from "lucide-react";
import { useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SimplePager } from "@/components/pager";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { MindmapWidget } from "@/components/mindmap/mindmap-widget";
import { TaArticlesDialog } from "@/components/intelligence/threat-actor-room/ta-articles-dialog";
import { TaProfileDialog } from "@/components/intelligence/threat-actor-room/ta-profile-dialog";
import type { TaProfileResponse } from "@/lib/api/loose-types";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";

type TAWatchlistOut = components["schemas"]["TAWatchlistOut"];
type TAWatchlistListResponse = components["schemas"]["TAWatchlistListResponse"];

const PAGE_SIZE_OPTIONS = [25, 50, 100];
const DORMANCY_STYLE: Record<string, { icon: string; color: string }> = {
  ACTIVE: { icon: "●", color: "text-success" },
  DORMANT: { icon: "●", color: "text-warning" },
  RESURGENT: { icon: "●", color: "text-destructive" },
};

/** Port bagian "TA WATCHLIST MANAGEMENT" (`ta.js:365-825`) -- card grid
 * (BUKAN tabel, beda dari Tracked/Whitelist), tiap card ngecek profile+
 * article count PARALEL (`Promise.allSettled` legacy -> `useQueries` di
 * sini). */
export function TaWatchlistPanel() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<"name" | "added_date">("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [pageSize, setPageSize] = useState(50);
  const [page, setPage] = useState(1);
  const [generating, setGenerating] = useState<string | null>(null);
  const [unwatchTarget, setUnwatchTarget] = useState<string | null>(null);
  const [articlesTarget, setArticlesTarget] = useState<string | null>(null);
  const [profileTarget, setProfileTarget] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["ta-room", "ta-watchlist", search, sortBy, sortDir, pageSize, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/ta/watchlist", {
        params: { query: { search: search || undefined, sort_by: sortBy, sort_dir: sortDir, page, page_size: pageSize } },
      });
      if (error) throw error;
      return data as TAWatchlistListResponse;
    },
  });

  const items = query.data?.items ?? [];

  const profileChecks = useQueries({
    queries: items.map((item) => ({
      queryKey: ["ta-room", "ta-profile", item.name],
      queryFn: async () => {
        const { data, error } = await api.GET("/api/ta/profile/{name}", { params: { path: { name: item.name } } });
        if (error) throw error;
        return data as unknown as TaProfileResponse;
      },
    })),
  });

  const articleCounts = useQueries({
    queries: items.map((item) => ({
      queryKey: ["ta-room", "ta-article-count", item.name],
      queryFn: async () => {
        const { data, error } = await api.GET("/api/articles", { params: { query: { threat_actor: [item.name], page_size: 1 } } });
        if (error) throw error;
        return data.total;
      },
    })),
  });

  async function generateProfile(name: string) {
    setGenerating(name);
    try {
      const { error } = await api.POST("/api/ta/profile/generate", { body: { name } });
      if (error) throw new Error(JSON.stringify(error));
      toast.success(`Profile generated for "${name}".`);
      await queryClient.invalidateQueries({ queryKey: ["ta-room", "ta-profile", name] });
      setProfileTarget(name);
    } catch (e) {
      toast.error(`Profile generation failed: ${(e as Error).message}`);
    } finally {
      setGenerating(null);
    }
  }

  async function unwatch(name: string) {
    try {
      const { error } = await api.DELETE("/api/ta/watchlist/{name}", { params: { path: { name } } });
      if (error) throw new Error(JSON.stringify(error));
      toast.success(`"${name}" removed from watchlist.`);
      await queryClient.invalidateQueries({ queryKey: ["ta-room", "ta-watchlist"] });
    } catch (e) {
      toast.error(`Failed to remove from watchlist: ${(e as Error).message}`);
    }
  }

  function openNavigator() {
    const layerUrl = encodeURIComponent(`${window.location.origin}/api/proxy/api/ta/watchlist/navigator-layer`);
    window.open(`https://mitre-attack.github.io/attack-navigator/#layerURL=${layerUrl}`, "_blank");
  }

  const total = query.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-2 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Search</Label>
          <Input
            placeholder="Actor name…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="w-48 font-mono text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Sort</Label>
          <div className="flex gap-1">
            <Select items={{ name: "Name", added_date: "Added Date" }} value={sortBy} onValueChange={(v) => v && setSortBy(v as "name" | "added_date")}>
              <SelectTrigger size="sm" className="w-32 font-mono text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="name" className="font-mono text-xs">
                  Name
                </SelectItem>
                <SelectItem value="added_date" className="font-mono text-xs">
                  Added Date
                </SelectItem>
              </SelectContent>
            </Select>
            <Button size="sm" variant="outline" className="px-2" onClick={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))}>
              {sortDir === "asc" ? "↑" : "↓"}
            </Button>
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Page Size</Label>
          <Select
            items={Object.fromEntries(PAGE_SIZE_OPTIONS.map((n) => [String(n), String(n)]))}
            value={String(pageSize)}
            onValueChange={(v) => {
              setPageSize(Number(v) || 50);
              setPage(1);
            }}
          >
            <SelectTrigger size="sm" className="w-20 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZE_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)} className="font-mono text-xs">
                  {n}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button size="sm" variant="outline" className="ml-auto" onClick={openNavigator}>
          ⧉ Open in Navigator
        </Button>
        <span className="font-mono text-xs text-muted-foreground">{total} watched</span>
      </div>

      {query.isPending && <p className="py-8 text-center text-xs text-muted-foreground">Loading…</p>}
      {query.isError && <p className="py-8 text-center text-xs text-destructive">Failed to load watchlist.</p>}
      {query.data && items.length === 0 && <p className="py-8 text-center text-xs text-muted-foreground">No groups in watchlist.</p>}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {items.map((item, i) => {
          const hasProfile = profileChecks[i]?.data?.exists ?? false;
          const artTotal = articleCounts[i]?.data ?? 0;
          const ds = DORMANCY_STYLE[item.dormancy_state] ?? DORMANCY_STYLE.DORMANT;
          return (
            <WatchlistCard
              key={item.id}
              item={item}
              dormancyIcon={ds.icon}
              dormancyColor={ds.color}
              hasProfile={hasProfile}
              articleTotal={artTotal}
              generating={generating === item.name}
              onGenerate={() => void generateProfile(item.name)}
              onViewProfile={() => setProfileTarget(item.name)}
              onOpenArticles={() => setArticlesTarget(item.name)}
              onUnwatch={() => setUnwatchTarget(item.name)}
            />
          );
        })}
      </div>

      <div className="mt-3 flex justify-center">
        <SimplePager page={page} totalPages={totalPages} totalLabel={`${total} total`} onPageChange={setPage} />
      </div>

      <ConfirmDialog
        open={unwatchTarget !== null}
        onOpenChange={(open) => !open && setUnwatchTarget(null)}
        title="Remove from Watchlist"
        description={unwatchTarget ? `Remove "${unwatchTarget}" from the watchlist?` : undefined}
        confirmLabel="Remove"
        onConfirm={() => unwatchTarget && void unwatch(unwatchTarget)}
      />

      <TaArticlesDialog actorName={articlesTarget} onClose={() => setArticlesTarget(null)} />
      <TaProfileDialog actorName={profileTarget} onClose={() => setProfileTarget(null)} />
    </div>
  );
}

function WatchlistCard({
  item,
  dormancyIcon,
  dormancyColor,
  hasProfile,
  articleTotal,
  generating,
  onGenerate,
  onViewProfile,
  onOpenArticles,
  onUnwatch,
}: {
  item: TAWatchlistOut;
  dormancyIcon: string;
  dormancyColor: string;
  hasProfile: boolean;
  articleTotal: number;
  generating: boolean;
  onGenerate: () => void;
  onViewProfile: () => void;
  onOpenArticles: () => void;
  onUnwatch: () => void;
}) {
  const can = useCan();
  return (
    <div className="rounded-xl border border-border bg-background p-3">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-foreground">{item.name}</span>
        <span className={`rounded-full border border-border bg-surface px-1.5 py-0.5 font-mono text-xs ${dormancyColor}`}>
          {dormancyIcon} {item.dormancy_state}
        </span>
      </div>
      <div className="mb-2 flex items-center gap-2 font-mono text-xs text-muted-foreground">
        <span>Added: {item.added_date || "—"}</span>
        <span className={`rounded-full border px-1.5 py-0.5 ${hasProfile ? "border-success/40 bg-success/10 text-success-text" : "border-border text-muted-foreground"}`}>
          {hasProfile ? "PROFILE" : "NO PROFILE"}
        </span>
      </div>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {can("manage_intel") && (
          <Button size="sm" variant="outline" className="h-6 px-2 text-xs" disabled={generating} onClick={onGenerate}>
            {generating ? "Generating…" : "AI Generate"}
          </Button>
        )}
        {hasProfile && (
          <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={onViewProfile}>
            <EyeIcon aria-hidden /> View Profile
          </Button>
        )}
        {can("manage_pir") && (
          <Button
            size="sm"
            variant="outline"
            aria-label="Remove from watchlist"
            className="ml-auto h-6 px-2 text-xs text-destructive"
            onClick={onUnwatch}
          >
            <XIcon aria-hidden />
          </Button>
        )}
      </div>
      <button
        type="button"
        disabled={articleTotal === 0}
        onClick={onOpenArticles}
        className="mb-2 w-full rounded-full border border-border bg-surface px-2 py-1 font-mono text-xs text-foreground disabled:opacity-40"
      >
        {articleTotal > 0 ? `${articleTotal} Article${articleTotal !== 1 ? "s" : ""}` : "No Articles"}
      </button>
      <MindmapWidget featureType="threat_actor" docId={item.name} title={item.name} />
    </div>
  );
}
