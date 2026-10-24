"use client";

import { geoBounds, geoCentroid, geoEquirectangular, geoPath } from "d3-geo";
import countries from "i18n-iso-countries";
import en from "i18n-iso-countries/langs/en.json";
import { useEffect, useMemo, useRef, useState } from "react";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import world from "world-atlas/countries-110m.json";

countries.registerLocale(en);

const ALIAS: Record<string, string> = { UK: "GB", EL: "GR" };
const STEP = 9; // jarak antar titik, dalam px CSS
const DOT_RADIUS = 0.8; // titik 1.6 px
const GLOW_FACTOR = 2.2;
const ANTARCTICA_ID = "010"; // id numerik world-atlas; tidak digambar (memenuhi baris bawah peta)
const COVER_CENTER_LON = 105; // mode "cover": bujur ini di tengah horizontal (APAC)

export interface WorldDotPoint {
  code: string; // ISO alpha-2 dari API, dinormalkan di sini (UK→GB, EL→GR)
  weight: number; // >= 0, menentukan radius glow
  tone: "incident" | "ransomware";
  ring?: boolean; // negara klien
  label: string; // nama aksesibel
}

/** Negara yang tidak punya poligon di world-atlas 110m (terlalu kecil): [bujur, lintang] ibu kota/pusat. */
const SMALL_STATES: Record<string, [number, number]> = {
  SG: [103.82, 1.35], HK: [114.17, 22.32], MO: [113.54, 22.2], BH: [50.55, 26.07],
  MV: [73.51, 4.18], MT: [14.51, 35.9], AD: [1.52, 42.55], MC: [7.42, 43.74],
  LI: [9.55, 47.17], SM: [12.46, 43.94], VA: [12.45, 41.9], SC: [55.49, -4.68],
  MU: [57.55, -20.35], BB: [-59.54, 13.19], AG: [-61.8, 17.06], DM: [-61.37, 15.41],
  GD: [-61.68, 12.12], KN: [-62.78, 17.36], LC: [-60.98, 13.91], VC: [-61.2, 13.25],
  TO: [-175.2, -21.18], WS: [-172.1, -13.76], KI: [173.0, 1.87], FM: [158.2, 6.92],
  MH: [171.2, 7.1], NR: [166.93, -0.52], PW: [134.58, 7.5], TV: [179.2, -8.52],
  CV: [-23.6, 15.1], KM: [43.87, -11.7], ST: [6.6, 0.34],
};

interface Size {
  w: number;
  h: number;
}

const normalize = (code: string) => ALIAS[code.toUpperCase()] ?? code.toUpperCase();

/** Warna dari token tema; dibaca ulang tiap gambar supaya ikut ganti terang/gelap. */
function readColors() {
  const s = getComputedStyle(document.documentElement);
  const get = (name: string) => s.getPropertyValue(name).trim();
  return {
    fg: get("--hero-foreground"),
    accent: get("--hero-accent"),
    eyebrow: get("--hero-eyebrow"),
  };
}

/**
 * Peta dunia dari titik-titik (canvas) mengisi parent-nya (`absolute inset-0`). Tanpa `points`
 * jadi latar dekoratif (login); dengan `points` jadi peta sinyal (dashboard). Tiap titik juga
 * punya `<button>` transparan supaya bisa difokus keyboard dan dibaca screen reader.
 */
export function WorldDots({
  points,
  className,
  fit = "contain",
  onPointFocus,
  onPointSelect,
}: {
  points?: WorldDotPoint[];
  className?: string;
  /** "contain": seluruh bola dunia muat. "cover": daratan mengisi dua dimensi, sisanya terpotong. */
  fit?: "contain" | "cover";
  onPointFocus?: (p: WorldDotPoint | null) => void;
  onPointSelect?: (p: WorldDotPoint) => void;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState<Size>({ w: 0, h: 0 });
  const [themeTick, setThemeTick] = useState(0);

  // Geometri dunia dibangun sekali per mount.
  const land = useMemo(() => {
    const topo = world as unknown as Topology;
    const all = feature(topo, topo.objects.countries as GeometryCollection);
    return {
      ...all,
      features: all.features.filter((f) => String(f.id) !== ANTARCTICA_ID),
    };
  }, []);

  const centroids = useMemo(() => {
    const m = new Map<string, [number, number]>();
    for (const f of land.features) {
      if (f.id === undefined) continue;
      const a2 = countries.numericToAlpha2(String(f.id));
      if (a2) m.set(a2, geoCentroid(f) as [number, number]);
    }
    return m;
  }, [land]);

  const projection = useMemo(() => {
    if (size.w <= 0 || size.h <= 0) return null;
    if (fit === "contain") {
      return geoEquirectangular().fitSize([size.w, size.h], { type: "Sphere" });
    }
    // Cover: skala terbesar dari lebar (360 derajat) dan tinggi (lintang daratan tanpa Antartika),
    // dipusatkan di tengah lintang daratan dan di bujur COVER_CENTER_LON; kelebihannya terpotong.
    const [[, latMin], [, latMax]] = geoBounds(land);
    const k = Math.max(size.w / (2 * Math.PI), size.h / (((latMax - latMin) * Math.PI) / 180));
    return geoEquirectangular()
      .scale(k)
      .rotate([-COVER_CENTER_LON, 0])
      .center([0, (latMin + latMax) / 2])
      .translate([size.w / 2, size.h / 2]);
  }, [size, fit, land]);

  // Titik yang kodenya tidak punya centroid dilewati.
  const placed = useMemo(() => {
    if (!projection || !points) return [];
    const out: { p: WorldDotPoint; x: number; y: number }[] = [];
    for (const p of points) {
      const code = normalize(p.code);
      const c = centroids.get(code) ?? SMALL_STATES[code];
      const xy = c ? projection(c) : null;
      if (xy) out.push({ p, x: xy[0], y: xy[1] });
    }
    return out;
  }, [projection, points, centroids]);

  // Ukuran mengikuti parent; tema berganti lewat class di <html>.
  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ w: Math.round(width), h: Math.round(height) });
    });
    ro.observe(box);
    const mo = new MutationObserver(() => setThemeTick((t) => t + 1));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => {
      ro.disconnect();
      mo.disconnect();
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !projection) return;
    const { w, h } = size;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    // Daratan digambar ke canvas luar layar (resolusi 1x), lalu disampel per STEP px.
    const off = document.createElement("canvas");
    off.width = w;
    off.height = h;
    const octx = off.getContext("2d", { willReadFrequently: true });
    if (!octx) return;
    octx.beginPath();
    geoPath(projection, octx)(land);
    octx.fill();
    const data = octx.getImageData(0, 0, w, h).data;

    const colors = readColors();
    ctx.globalAlpha = 0.32;
    ctx.fillStyle = colors.fg;
    ctx.beginPath();
    for (let y = STEP / 2; y < h; y += STEP) {
      for (let x = STEP / 2; x < w; x += STEP) {
        if (data[(Math.floor(y) * w + Math.floor(x)) * 4 + 3] > 127) {
          ctx.moveTo(x + DOT_RADIUS, y);
          ctx.arc(x, y, DOT_RADIUS, 0, Math.PI * 2);
        }
      }
    }
    ctx.fill();
    ctx.globalAlpha = 1;

    const maxWeight = Math.max(1, ...placed.map(({ p }) => p.weight));
    for (const { p, x, y } of placed) {
      const r = 4 + (14 * p.weight) / maxWeight;
      const color = p.tone === "incident" ? colors.accent : colors.eyebrow;
      const glow = ctx.createRadialGradient(x, y, 0, x, y, r * GLOW_FACTOR);
      glow.addColorStop(0, color);
      glow.addColorStop(1, "transparent");
      ctx.globalAlpha = 0.35;
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(x, y, r * GLOW_FACTOR, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(x, y, Math.max(2, r / 3), 0, Math.PI * 2);
      ctx.fill();
      if (p.ring) {
        ctx.strokeStyle = colors.fg;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
  }, [projection, size, land, placed, themeTick]);

  return (
    <div ref={boxRef} className={`absolute inset-0 ${className ?? ""}`}>
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-hidden />
      {placed.map(({ p, x, y }) => (
        <button
          key={`${p.code}-${p.tone}`}
          type="button"
          aria-label={p.label}
          className="absolute size-6 -translate-x-1/2 -translate-y-1/2 rounded-full bg-transparent focus-visible:ring-3 focus-visible:ring-focus focus-visible:outline-none"
          style={{ left: x, top: y }}
          onMouseEnter={() => onPointFocus?.(p)}
          onMouseLeave={() => onPointFocus?.(null)}
          onFocus={() => onPointFocus?.(p)}
          onBlur={() => onPointFocus?.(null)}
          onClick={() => onPointSelect?.(p)}
        />
      ))}
    </div>
  );
}
