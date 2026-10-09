"use client";

import { geoNaturalEarth1, geoPath } from "d3-geo";
import countries from "i18n-iso-countries";
import en from "i18n-iso-countries/langs/en.json";
import { useMemo, useRef, useState } from "react";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import world from "world-atlas/countries-110m.json";

countries.registerLocale(en);

const W = 960;
const H = 480;
const ALIAS: Record<string, string> = { UK: "GB", EL: "GR" };

interface CountryDatum {
  name: string; // kode ISO alpha-2 dari API
  count: number;
}

interface Hover {
  code: string;
  x: number;
  y: number;
}

const normalize = (code: string) => ALIAS[code.toUpperCase()] ?? code.toUpperCase();
const countryName = (code: string) => countries.getName(code, "en") ?? code;

/** Peta dunia choropleth. Hover di negara memunculkan nama dan jumlahnya. */
export function CountryMap({ data, unit = "articles" }: { data: CountryDatum[]; unit?: string }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<Hover | null>(null);

  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const d of data) {
      const c = normalize(d.name);
      m.set(c, (m.get(c) ?? 0) + d.count);
    }
    return m;
  }, [data]);
  const max = Math.max(1, ...counts.values());

  const shapes = useMemo(() => {
    const topo = world as unknown as Topology;
    const fc = feature(topo, topo.objects.countries as GeometryCollection);
    const projection = geoNaturalEarth1().fitSize([W, H], { type: "Sphere" });
    const path = geoPath(projection);
    return fc.features.map((f, i) => ({
      // N. Cyprus, Somaliland, dan Kosovo tidak punya `id` numerik di world-atlas. `String(undefined)`
      // membuat ketiganya berkunci "undefined" dan React protes key kembar tiap peta dirender. Id
      // pengganti tidak pernah cocok dengan kode ISO di `numericToCode`, jadi ketiganya tetap abu-abu
      // seperti sebelumnya.
      id: f.id === undefined ? `no-id-${i}` : String(f.id),
      d: path(f) ?? "",
    }));
  }, []);

  const numericToCode = useMemo(() => {
    const m = new Map<string, string>();
    for (const code of counts.keys()) {
      const n = countries.alpha2ToNumeric(code);
      if (n) m.set(n.padStart(3, "0"), code);
    }
    return m;
  }, [counts]);

  const fillFor = (count: number) =>
    `color-mix(in srgb, var(--info) ${Math.round(25 + Math.sqrt(count / max) * 70)}%, var(--surface))`;

  function pointerAt(code: string, e: React.PointerEvent | React.MouseEvent) {
    const box = boxRef.current?.getBoundingClientRect();
    if (!box) return;
    setHover({ code, x: e.clientX - box.left, y: e.clientY - box.top });
  }

  const hoverCount = hover ? (counts.get(hover.code) ?? 0) : 0;

  return (
    <div ref={boxRef} className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="World map of mentioned countries. Hover a country to see its name and count."
        className="h-auto w-full"
      >
        {shapes.map((s) => {
          const code = numericToCode.get(s.id);
          const count = code ? (counts.get(code) ?? 0) : 0;
          return (
            <path
              key={s.id}
              d={s.d}
              fill={count > 0 ? fillFor(count) : "var(--border)"}
              stroke="var(--surface)"
              strokeWidth={0.6}
              className={code ? "cursor-pointer transition-opacity duration-150 hover:opacity-80" : undefined}
              onPointerMove={code ? (e) => pointerAt(code, e) : undefined}
              onPointerLeave={code ? () => setHover(null) : undefined}
            />
          );
        })}
      </svg>

      <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground" aria-hidden>
        <span>Fewer</span>
        <span
          className="h-2 w-28 rounded-full"
          style={{ background: `linear-gradient(to right, ${fillFor(0.01)}, ${fillFor(max)})` }}
        />
        <span>More ({max})</span>
      </div>

      {hover && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-xl border border-border bg-popover px-3 py-1.5 text-sm whitespace-nowrap text-popover-foreground shadow-lg"
          style={{ left: hover.x, top: hover.y - 10 }}
        >
          <span className="font-semibold">{countryName(hover.code)}</span>
          <span className="ml-2 text-muted-foreground tabular-nums">
            {hoverCount} {unit}
          </span>
        </div>
      )}
    </div>
  );
}
