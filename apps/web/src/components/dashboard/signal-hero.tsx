"use client";

import countries from "i18n-iso-countries";
import en from "i18n-iso-countries/langs/en.json";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { WorldDots, type WorldDotPoint } from "@/components/world-dots";
import { useDashboardAttention, useDashboardMap } from "./use-dashboard-overview";

countries.registerLocale(en);

const ALIAS: Record<string, string> = { UK: "GB", EL: "GR" };
const normalize = (code: string) => ALIAS[code.toUpperCase()] ?? code.toUpperCase();
const countryName = (code: string) => countries.getName(normalize(code), "en") ?? code;

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

/**
 * Hero dashboard: peta sinyal (insiden + korban ransomware per negara) di kiri, brief dan tiga
 * aksi paling mendesak di kanan. Peta dan brief dari dua endpoint terpisah; salah satunya gagal
 * tidak menyembunyikan yang lain.
 */
export function SignalHero({ days }: { days: number | null }) {
  const router = useRouter();
  const map = useDashboardMap(days);
  const attention = useDashboardAttention(days);
  const mapBoxRef = useRef<HTMLDivElement>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const periodLabel = days ? `${days} hari terakhir` : "Semua waktu";

  // Memoise: array baru tiap render membangun ulang raster daratan di WorldDots.
  const { points, details } = useMemo(() => {
    const clientCountries = new Set((map.data?.client_countries ?? []).map(normalize));
    const details = new Map<WorldDotPoint, Detail>();
    const points: WorldDotPoint[] = [];
    for (const m of map.data?.points ?? []) {
      const name = countryName(m.country_code);
      const point: WorldDotPoint = {
        code: m.country_code,
        weight: m.incidents + m.ransomware_victims,
        tone: m.incidents >= m.ransomware_victims ? "incident" : "ransomware",
        ring: clientCountries.has(normalize(m.country_code)),
        label: `${name}: ${m.incidents} insiden, ${m.ransomware_victims} korban ransomware`,
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

  const topPoints = useMemo(() => [...points].sort((a, b) => b.weight - a.weight).slice(0, 10), [points]);

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
    const cx = b.left - r.left + b.width / 2;
    const half = 100; // setengah lebar tooltip, perkiraan
    setFocus({
      detail,
      data: map.data,
      x: Math.min(Math.max(cx, half), Math.max(half, r.width - half)),
      y: b.top - r.top + (b.top - r.top < 90 ? b.height : 0),
      below: b.top - r.top < 90,
    });
  }

  if (map.isPending && attention.isPending) {
    return <Skeleton className="min-h-[420px] w-full rounded-3xl" />;
  }

  const shown = focus && focus.data === map.data ? focus : null;
  const att = attention.data;
  const empty = map.data && map.data.points.length === 0;

  return (
    <section
      aria-label="Signal map"
      className="grid min-h-[420px] overflow-hidden rounded-3xl bg-hero text-hero-foreground lg:grid-cols-[1fr_360px]"
    >
      <div className="relative min-h-[320px] lg:min-h-0">
        <div ref={mapBoxRef} className="absolute inset-0">
          <WorldDots
            points={points}
            onPointFocus={onPointFocus}
            onPointSelect={(p) => router.push(`/newsroom?country=${encodeURIComponent(p.code)}`)}
          />
          {shown && (
            <div
              role="status"
              className={`pointer-events-none absolute z-10 -translate-x-1/2 rounded-xl bg-card px-3 py-2 text-sm text-card-foreground shadow-lg ${shown.below ? "" : "-translate-y-full"}`}
              style={{ left: shown.x, top: shown.below ? shown.y + 8 : shown.y - 8 }}
            >
              <div className="font-semibold">{countryName(shown.detail.point.code)}</div>
              <div className="text-xs whitespace-nowrap tabular-nums">
                {shown.detail.incidents} insiden · {shown.detail.victims} korban ransomware
              </div>
              {(shown.detail.topActor || shown.detail.topIndustry) && (
                <div className="text-xs whitespace-nowrap text-muted-foreground">
                  Teratas: {[shown.detail.topActor, shown.detail.topIndustry].filter(Boolean).join(", ")}
                </div>
              )}
            </div>
          )}
        </div>
        <div className="pointer-events-none absolute top-5 left-6 right-6">
          <h2 className="text-sm font-semibold">Signal map · {periodLabel}</h2>
          <p className="mt-0.5 text-xs text-hero-muted">
            Ukuran titik = artikel insiden + korban ransomware per negara
          </p>
        </div>
        <ul className="pointer-events-none absolute bottom-4 left-6 flex flex-wrap gap-x-4 gap-y-1 text-xs text-hero-muted">
          <li className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-hero-accent" aria-hidden />
            Insiden
          </li>
          <li className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-hero-eyebrow" aria-hidden />
            Ransomware
          </li>
          <li className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full border border-hero-foreground" aria-hidden />
            Negara klien (cincin)
          </li>
        </ul>
        {map.isError && (
          <p className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-hero-muted">
            Gagal memuat peta.
          </p>
        )}
        {empty && (
          <p className="pointer-events-none absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-hero-muted">
            Belum ada insiden dengan negara pada periode ini.
          </p>
        )}
        <ol className="sr-only">
          {topPoints.map((p) => (
            <li key={`${p.code}-${p.tone}`}>{p.label}</li>
          ))}
        </ol>
      </div>

      <aside className="flex flex-col gap-4 bg-hero-panel p-6">
        <div className="text-xs font-semibold tracking-widest text-hero-eyebrow uppercase">Brief</div>
        {attention.isError && !att && <p className="text-sm text-hero-muted">Gagal memuat brief.</p>}
        {attention.isPending && <Skeleton className="h-40 w-full bg-hero-foreground/10" />}
        {att && (
          <>
            <div>
              <p className="text-[17px] leading-snug font-[650]">{att.brief.headline}</p>
              <p className="mt-2 text-sm text-hero-muted">{att.brief.detail}</p>
              <Link href="/recap" className="mt-2 inline-block text-sm text-hero-accent hover:underline">
                Recap mingguan →
              </Link>
            </div>
            <div className="mt-auto flex flex-col divide-y divide-hero-foreground/15">
              <ActionRow
                href="/cve"
                value={att.kev_in_stack}
                label="CVE KEV kena tech stack"
                sub={`${att.kev_without_ticket} tanpa tiket`}
              />
              <ActionRow
                href="/newsroom?rubric=ransomware"
                value={att.ransomware_in_client_scope}
                label="Korban ransomware di negara klien"
              />
              <ActionRow
                href="/newsroom?rubric=watchlist"
                value={att.watchlist_hits + att.pir_hits}
                label="Hit watchlist / PIR"
                sub={`${att.pir_hits} PIR`}
              />
            </div>
          </>
        )}
      </aside>
    </section>
  );
}

function ActionRow({ href, value, label, sub }: { href: string; value: number; label: string; sub?: string }) {
  return (
    <Link href={href} className="flex items-center gap-3 py-3 hover:text-hero-accent">
      <span className="w-12 text-3xl leading-none font-extrabold tabular-nums">{value.toLocaleString()}</span>
      <span className="text-sm">
        {label}
        {sub && <span className="block text-xs text-hero-muted">{sub}</span>}
      </span>
    </Link>
  );
}
