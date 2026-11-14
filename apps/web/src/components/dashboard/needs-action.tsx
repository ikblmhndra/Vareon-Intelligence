"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import { useTechStackNames, useWatchlistNames } from "@/components/newsroom/rubric-queries";
import { heroLinkClass, HeroPanel } from "@/components/ui/hero-panel";
import { MeterBar } from "@/components/ui/meter-bar";
import { Skeleton } from "@/components/ui/skeleton";
import { inView, type WorldDotPoint, type WorldView } from "@/components/world-dots";
import { useActiveClientName } from "@/lib/auth/client-id";
import { useCan } from "@/lib/auth/permissions";
import { countryName, normalizeCountry } from "@/lib/dashboard/countries";
import { periodInfo, type PeriodKey } from "@/lib/dashboard/period";
import { cn } from "@/lib/utils";

import {
  useDashboardAttention,
  useDashboardMap,
  type DashboardAttention,
} from "./use-dashboard-overview";

// Canvas peta hanya jalan di browser; render server dilewati seperti hero lama.
const WorldDots = dynamic(() => import("@/components/world-dots").then((m) => m.WorldDots), {
  ssr: false,
});

interface Detail {
  point: WorldDotPoint;
  incidents: number;
  victims: number;
  topActor?: string | null;
  topIndustry?: string | null;
}

interface Focus {
  detail: Detail;
  x: number;
  y: number;
  data: unknown; // data peta saat fokus; tooltip dibuang bila data berganti (ganti periode)
  below: boolean; // titik dekat tepi atas: tooltip di bawah titik supaya tidak terpotong
}

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
  const router = useRouter();
  const mapBoxRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<WorldView>("apac");
  const [focus, setFocus] = useState<Focus | null>(null);

  // Memoise: array baru tiap render membangun ulang raster daratan di WorldDots.
  const { points, details } = useMemo(() => {
    const clientCountries = new Set((map.data?.client_countries ?? []).map(normalizeCountry));
    const details = new Map<WorldDotPoint, Detail>();
    const points: WorldDotPoint[] = [];
    for (const m of map.data?.points ?? []) {
      // Baris tanpa kode negara (korban ransomware) tidak punya koordinat: tidak dikirim ke peta.
      if (!m.country_code) continue;
      const point: WorldDotPoint = {
        code: m.country_code,
        weight: m.incidents + m.ransomware_victims,
        tone: m.incidents >= m.ransomware_victims ? "incident" : "ransomware",
        ring: clientCountries.has(normalizeCountry(m.country_code)),
        label: `${countryName(m.country_code)}: ${m.incidents} incidents, ${m.ransomware_victims} ransomware victims`,
      };
      points.push(point);
      details.set(point, {
        point,
        incidents: m.incidents,
        victims: m.ransomware_victims,
        topActor: m.top_actor,
        topIndustry: m.top_industry,
      });
    }
    return { points, details };
  }, [map.data]);

  // Hanya titik yang terlihat di tampilan aktif; daftar sr-only dan overlay mengikutinya.
  const inViewTop = useMemo(
    () => points.filter((p) => inView(p.code, view)).sort((a, b) => b.weight - a.weight),
    [points, view],
  );
  const topPoints = inViewTop.slice(0, 10);
  const topCountries = inViewTop.slice(0, 4);

  // WorldDots hanya melaporkan titiknya; posisi tooltip dibaca dari tombol titik itu di DOM.
  function onPointFocus(p: WorldDotPoint | null) {
    const detail = p ? details.get(p) : undefined;
    const box = mapBoxRef.current;
    if (!p || !detail || !box) return setFocus(null);
    const btn = Array.from(box.querySelectorAll("button")).find(
      (b) => b.getAttribute("aria-label") === p.label,
    );
    if (!btn) return setFocus(null);
    const b = btn.getBoundingClientRect();
    const r = box.getBoundingClientRect();
    const half = 100; // setengah lebar tooltip, perkiraan
    setFocus({
      detail,
      data: map.data,
      x: Math.min(Math.max(b.left - r.left + b.width / 2, half), Math.max(half, r.width - half)),
      y: b.top - r.top + (b.top - r.top < 90 ? b.height : 0),
      below: b.top - r.top < 90,
    });
  }
  const shown = focus && focus.data === map.data ? focus : null;

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
        <Skeleton aria-hidden className="h-[420px] w-full rounded-lg bg-hero" />
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
          <div className="relative h-[380px] w-[500px] max-w-full overflow-hidden rounded-md">
            <div ref={mapBoxRef} className="absolute inset-0">
              {map.data && points.length > 0 && (
                <WorldDots
                  points={points}
                  view={view}
                  onPointFocus={onPointFocus}
                  onPointSelect={(p) => router.push(`/newsroom?country=${encodeURIComponent(p.code)}`)}
                />
              )}
              {shown && (
                <div
                  role="status"
                  className={cn(
                    "pointer-events-none absolute z-10 -translate-x-1/2 rounded-md bg-hero-panel px-3 py-2 text-sm text-hero-foreground shadow-lg",
                    !shown.below && "-translate-y-full",
                  )}
                  style={{ left: shown.x, top: shown.below ? shown.y + 8 : shown.y - 8 }}
                >
                  <div className="font-semibold">{countryName(shown.detail.point.code)}</div>
                  <div className="text-xs whitespace-nowrap tabular-nums">
                    {shown.detail.incidents} incidents · {shown.detail.victims} ransomware victims
                  </div>
                  {(shown.detail.topActor || shown.detail.topIndustry) && (
                    <div className="text-xs whitespace-nowrap text-hero-muted">
                      Top: {[shown.detail.topActor, shown.detail.topIndustry].filter(Boolean).join(", ")}
                    </div>
                  )}
                </div>
              )}
            </div>
            <div className="pointer-events-none absolute top-0 right-0 left-0 flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-hero-foreground">Signal map</h3>
                <p className="text-xs text-hero-muted">Incidents &amp; ransomware victims, {words}</p>
              </div>
              <div className="pointer-events-auto flex gap-3 text-xs">
                {(["apac", "world"] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    aria-pressed={view === v}
                    onClick={() => {
                      setView(v);
                      setFocus(null);
                    }}
                    className={cn(heroLinkClass, view === v ? "font-semibold underline" : "text-hero-muted")}
                  >
                    {v === "apac" ? "APAC" : "World"}
                  </button>
                ))}
              </div>
            </div>
            {map.isPending && <Skeleton aria-hidden className="absolute inset-0 bg-hero-panel" />}
            <ul className="pointer-events-none absolute bottom-0 left-0 flex flex-wrap gap-x-4 gap-y-1 text-xs text-hero-muted">
              <li className="flex items-center gap-1.5">
                <span className="size-2 rounded-full bg-hero-accent" aria-hidden />
                Incidents
              </li>
              <li className="flex items-center gap-1.5">
                <span className="size-2 rounded-full bg-hero-eyebrow" aria-hidden />
                Ransomware
              </li>
              <li className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-full border border-hero-foreground" aria-hidden />
                Your countries (ring)
              </li>
            </ul>
            {topCountries.length > 0 && (
              <div className="pointer-events-none absolute right-0 bottom-0 w-52 rounded-md bg-hero-panel p-3">
                <p className="text-2xs font-bold tracking-[0.12em] text-hero-eyebrow uppercase">Top countries</p>
                <ul className="mt-2 flex flex-col gap-1.5 text-xs text-hero-foreground">
                  {topCountries.map((p) => (
                    <li key={`${p.code}-${p.tone}`} className="flex items-center gap-2">
                      <span className="w-20 shrink-0 truncate">{countryName(p.code)}</span>
                      <MeterBar
                        onHero
                        value={p.weight}
                        max={topCountries[0].weight}
                        aria-label={countryName(p.code)}
                        className="min-w-0 flex-1"
                      />
                      <span className="font-code tabular-nums">{num(p.weight)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {map.isError && !map.data && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center text-sm">
                <p className="font-semibold text-hero-foreground">Could not load the map</p>
                <p>{map.error instanceof Error && map.error.message ? map.error.message : "The request failed."}</p>
                <button type="button" onClick={() => map.refetch()} className={cn(heroLinkClass, "font-semibold")}>
                  Retry
                </button>
              </div>
            )}
            {map.data && points.length === 0 && (
              <p className="pointer-events-none absolute inset-0 flex items-center justify-center px-6 text-center text-sm">
                No incidents with a country in this period.
              </p>
            )}
            <ol className="sr-only">
              {topPoints.map((p) => (
                <li key={`${p.code}-${p.tone}`}>{p.label}</li>
              ))}
            </ol>
          </div>
        </div>
      </HeroPanel>
    </section>
  );
}
