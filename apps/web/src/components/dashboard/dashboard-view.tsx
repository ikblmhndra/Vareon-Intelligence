"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

import { CveWatchlist } from "@/components/dashboard/cve-watchlist";
import { ByTheNumbers } from "@/components/dashboard/by-the-numbers";
import { LeadStory } from "@/components/dashboard/lead-story";
import { MonthCharts } from "@/components/dashboard/month-charts";
import { MoreSection } from "@/components/dashboard/more-section";
import { MustRead } from "@/components/dashboard/must-read";
import { NeedsAction } from "@/components/dashboard/needs-action";
import { Trending } from "@/components/dashboard/trending";
import { useArticleOpener } from "@/components/dashboard/article-opener";
import { PageHeader } from "@/components/page-header";
import { useAuth } from "@/components/providers/auth-provider";
import { Checkbox } from "@/components/ui/checkbox";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { StatePanel } from "@/components/ui/state-panel";
import { useActiveClientName } from "@/lib/auth/client-id";
import { useCan } from "@/lib/auth/permissions";
import { PERIODS, parsePeriod, periodHref, type PeriodKey } from "@/lib/dashboard/period";

const noopSubscribe = () => () => {};
// String primitif: snapshot stabil antar panggilan. Tanggal hanya dibaca di snapshot klien, bukan saat render.
const todaySnapshot = () =>
  new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric" }).format(new Date());

const PERIOD_OPTIONS = PERIODS.map((p) => ({ value: p.key, label: p.label }));

/** Cangkang Dashboard 5a: header, periode di URL, toggle berita ancaman, gerbang view_news. */
export function DashboardView() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { user } = useAuth();
  const can = useCan();
  const clientName = useActiveClientName();
  const title = useSyncExternalStore(noopSubscribe, todaySnapshot, () => "Dashboard");
  const [threatOnly, setThreatOnly] = useState(true);
  const { openArticle, host } = useArticleOpener();

  // Periode dibaca dari URL tiap render, tanpa state tiruan: URL satu-satunya sumber.
  const period = parsePeriod(searchParams.get("period"));
  const kicker = clientName ? `THREAT BRIEFING · ${clientName.toUpperCase()}` : "THREAT BRIEFING";

  function onPeriod(key: PeriodKey) {
    const qs = searchParams.toString();
    const next = periodHref(pathname, new URLSearchParams(qs), key);
    // Jangan menavigasi ke URL yang sama: menumpuk riwayat dan memicu render sia-sia.
    if (next === pathname + (qs ? "?" + qs : "")) return;
    router.replace(next, { scroll: false });
  }

  if (!can("view_news")) {
    return (
      <div className="pb-10">
        <PageHeader kicker={kicker} title={title} />
        <StatePanel
          variant="no-access"
          title="Dashboard needs the view_news permission"
          description={`Your role (${user?.role ?? "unknown"}) does not have it.`}
        />
      </div>
    );
  }

  return (
    <div className="pb-10">
      <PageHeader
        kicker={kicker}
        title={title}
        actions={
          <div className="flex flex-wrap items-center gap-4">
            <SegmentedControl aria-label="Period" options={PERIOD_OPTIONS} value={period} onChange={onPeriod} />
            <label className="flex items-center gap-2 text-xs text-foreground">
              <Checkbox checked={threatOnly} onCheckedChange={(v) => setThreatOnly(v === true)} />
              Threat news only
            </label>
          </div>
        }
      />
      <div className="space-y-6">
        <NeedsAction period={period} />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,820fr)_minmax(0,468fr)]">
          <LeadStory period={period} openArticle={openArticle} />
          <ByTheNumbers period={period} threatOnly={threatOnly} />
        </div>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,820fr)_minmax(0,468fr)]">
          <MustRead period={period} openArticle={openArticle} />
          <Trending period={period} />
        </div>
        <MonthCharts threatOnly={threatOnly} />
        <CveWatchlist period={period} />
        <MoreSection period={period} threatOnly={threatOnly} />
      </div>
      {host}
    </div>
  );
}
