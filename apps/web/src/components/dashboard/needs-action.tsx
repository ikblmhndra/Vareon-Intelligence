"use client";

import Link from "next/link";

import { useTechStackNames, useWatchlistNames } from "@/components/newsroom/rubric-queries";
import { heroLinkClass, HeroPanel } from "@/components/ui/hero-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveClientName } from "@/lib/auth/client-id";
import { useCan } from "@/lib/auth/permissions";
import { countryName } from "@/lib/dashboard/countries";
import { periodInfo, type PeriodKey } from "@/lib/dashboard/period";
import { cn } from "@/lib/utils";

import {
  useDashboardAttention,
  useDashboardMap,
  type DashboardAttention,
} from "./use-dashboard-overview";

const num = (n: number) => n.toLocaleString("en-US");

interface Row {
  key: string;
  value: number;
  title: string;
  second: string;
  href: string;
}

/** Tiga baris aksi (spec 6.2). Bagian kosong pada baris kedua dibuang sebelum digabung " · ". */
function buildRows(a: DashboardAttention, days: number | null, words: string): Row[] {
  // Newsroom hanya menerima period 1/7/30; 90 dan semua waktu dibuka tanpa filter periode.
  const period = days === 1 || days === 7 || days === 30 ? `&period=${days}` : "";
  const countries = a.client_countries;
  const join = (parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" · ");

  let ransomTitle = "Ransomware victims in your countries";
  if (countries.length === 1) ransomTitle = `Ransomware victims in ${countryName(countries[0])}`;
  else if (countries.length > 1) ransomTitle = `Ransomware victims in your ${countries.length} countries`;

  const prev = a.ransomware_prev_in_client_scope;
  const d = prev === null ? null : a.ransomware_in_client_scope - prev;
  let compare: string | null = null;
  if (d !== null) {
    compare = d > 0 ? `Up ${num(d)} from the previous ${words}` : d < 0 ? `Down ${num(-d)} from the previous ${words}` : `Same as the previous ${words}`;
  }
  const top = a.ransomware_client_top_industry;

  return [
    {
      key: "kev",
      value: a.kev_in_stack,
      title: "KEV CVEs hit your tech stack",
      second:
        a.kev_in_stack === 0
          ? "None open right now"
          : join([
              "Open now",
              a.kev_tech.length > 0 && a.kev_tech.join(", "),
              a.kev_without_ticket > 0 && `${num(a.kev_without_ticket)} without a ticket`,
            ]),
      href: "/cve",
    },
    {
      key: "ransomware",
      value: a.ransomware_in_client_scope,
      title: ransomTitle,
      second:
        countries.length === 0
          ? "No country is set for this client"
          : join([compare, top && `${num(top.count)} in ${top.name}`]),
      href: `/newsroom?rubric=ransomware${countries.length === 1 ? `&country=${encodeURIComponent(countries[0])}` : ""}${period}`,
    },
    {
      key: "watchlist",
      value: a.watchlist_hits,
      title: "Articles matching your watchlist",
      second: join([
        a.watchlist_top.length > 0 && a.watchlist_top.join(", "),
        `${num(a.pir_hits)} active ${a.pir_hits === 1 ? "PIR" : "PIRs"} with new articles`,
      ]),
      href: `/newsroom?rubric=watchlist${period}`,
    },
  ];
}

export function NeedsAction({ period }: { period: PeriodKey }) {
  const { days, words, suffix } = periodInfo(period);
  const attention = useDashboardAttention(days);
  const map = useDashboardMap(days);
  const can = useCan();
  const client = useActiveClientName() ?? "your organisation";
  const tech = useTechStackNames(can("view_cve"));
  const watch = useWatchlistNames(can("view_ta"));

  const noData =
    can("view_cve") &&
    can("view_ta") &&
    tech.isSuccess &&
    watch.isSuccess &&
    tech.data.length === 0 &&
    watch.data.length === 0;

  const att = attention.data;
  const rows = att ? buildRows(att, days, words) : [];
  const n = rows.filter((r) => r.value > 0).length;
  const headline = `${n === 0 ? "No signals" : n === 1 ? "1 signal" : `${n} signals`} for ${client} ${suffix}`;

  if (attention.isPending && map.isPending) {
    return (
      <section aria-label="Needs action">
        <Skeleton aria-hidden className="h-[420px] w-full rounded-lg bg-hero-panel" />
      </section>
    );
  }

  let left;
  if (noData) {
    left = (
      <div className="flex flex-col items-start gap-3">
        <p>
          Articles are already arriving. Matching starts once a tech stack and a watchlist are set: add the
          products you run and the actors you track, and this panel fills in.
        </p>
        <Link
          href="/cve"
          className="rounded-md bg-hero-foreground px-4 py-2 text-sm font-semibold text-hero outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-hero"
        >
          Set up tech stack
        </Link>
      </div>
    );
  } else if (attention.isError && !att) {
    left = (
      <div className="flex flex-col items-start gap-2">
        <p className="font-semibold text-hero-foreground">Could not load the signals</p>
        <p>{attention.error instanceof Error && attention.error.message ? attention.error.message : "The request failed."}</p>
        <button
          type="button"
          onClick={() => attention.refetch()}
          className={cn(heroLinkClass, "font-semibold")}
        >
          Retry
        </button>
      </div>
    );
  } else if (attention.isPending) {
    left = <Skeleton aria-hidden className="h-48 w-full bg-hero-panel" />;
  } else {
    left = (
      <ul className={cn("flex flex-col divide-y divide-hero-foreground/15", attention.isPlaceholderData && "opacity-60")}>
        {rows.map((r) => (
          <li key={r.key}>
            <Link
              href={r.href}
              aria-label={`${r.title}: ${num(r.value)}. Open`}
              className={cn(heroLinkClass, "flex items-center gap-4 py-3 no-underline hover:no-underline")}
            >
              <span className="min-w-16 shrink-0 font-code text-3xl leading-none font-bold text-hero-foreground tabular-nums">
                {num(r.value)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-semibold text-hero-foreground">{r.title}</span>
                {r.second && <span className="block text-hero-muted">{r.second}</span>}
              </span>
              <span className="shrink-0">Open →</span>
            </Link>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <section aria-label="Needs action">
      <HeroPanel
        kicker={noData ? "GET STARTED" : "NEEDS ACTION"}
        title={noData ? `Nothing is matched to ${client} yet` : att ? headline : "Needs action"}
      >
        <div className="grid gap-6 lg:grid-cols-[minmax(0,752fr)_500px]">
          <div>{left}</div>
          {/* Task 15: peta sinyal mengisi kolom ini. */}
          <div className="h-[380px] w-[500px] max-w-full" />
        </div>
      </HeroPanel>
    </section>
  );
}
