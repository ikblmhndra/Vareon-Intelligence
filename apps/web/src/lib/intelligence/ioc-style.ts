import { tint } from "@/lib/tint";

export interface IocChipStyle {
  label: string;
  bg: string;
  border: string;
  color: string;
}

/** Port `_IOC_TYPE_STYLE` (`ioc_mgmt.js:10-20`) -- 7 tipe IOC, warna
 * literal apa adanya (bukan token Tailwind diskrit) karena nuansanya
 * sengaja dibedain per tipe buat scan cepat di tabel gede, sama
 * keputusan kayak heatmap MITRE Grup G3. */
export const IOC_TYPE_STYLE: Record<string, IocChipStyle> = {
  ip: { label: "IP", bg: tint("var(--severity-critical)", 12), border: tint("var(--severity-critical)", 35), color: "var(--severity-critical-text)" },
  domain: { label: "DOMAIN", bg: tint("var(--severity-medium)", 12), border: tint("var(--severity-medium)", 35), color: "var(--severity-medium-text)" },
  url: { label: "URL", bg: tint("var(--info)", 12), border: tint("var(--info)", 35), color: "var(--info-text)" },
  email: { label: "EMAIL", bg: tint("var(--info)", 12), border: tint("var(--info)", 35), color: "var(--info-text)" },
  sha256: { label: "SHA256", bg: tint("var(--tag-violet)", 20), border: tint("var(--tag-violet)", 40), color: "var(--tag-violet-text)" },
  sha1: { label: "SHA1", bg: tint("var(--tag-violet)", 15), border: tint("var(--tag-violet)", 30), color: "var(--tag-violet-text)" },
  md5: { label: "MD5", bg: tint("var(--tag-violet)", 15), border: tint("var(--tag-violet)", 30), color: "var(--tag-violet-text)" },
};

export function iocTypeStyle(type: string): IocChipStyle {
  return IOC_TYPE_STYLE[type] ?? { label: type.toUpperCase(), bg: tint("var(--muted-foreground)", 5), border: tint("var(--muted-foreground)", 15), color: "var(--muted-foreground)" };
}

export const ACTIONABILITY_STYLE: Record<string, IocChipStyle> = {
  block_now: { label: "BLOCK NOW", bg: tint("var(--severity-critical)", 15), border: tint("var(--severity-critical)", 45), color: "var(--severity-critical-text)" },
  investigate: { label: "INVESTIGATE", bg: tint("var(--severity-high)", 12), border: tint("var(--severity-high)", 40), color: "var(--severity-high-text)" },
  monitor: { label: "MONITOR", bg: tint("var(--severity-medium)", 12), border: tint("var(--severity-medium)", 35), color: "var(--severity-medium-text)" },
  archive: { label: "ARCHIVE", bg: tint("var(--muted-foreground)", 4), border: tint("var(--muted-foreground)", 15), color: "var(--muted-foreground)" },
};

export function actionabilityStyle(label: string): IocChipStyle {
  return ACTIONABILITY_STYLE[label] ?? ACTIONABILITY_STYLE.archive;
}

export function confidenceStyle(score: number): IocChipStyle {
  if (score >= 75) return { label: String(score), bg: tint("var(--success)", 15), border: tint("var(--success)", 40), color: "var(--success-text)" };
  if (score >= 40) return { label: String(score), bg: tint("var(--severity-high)", 12), border: tint("var(--severity-high)", 40), color: "var(--severity-high-text)" };
  return { label: String(score), bg: tint("var(--muted-foreground)", 5), border: tint("var(--muted-foreground)", 15), color: "var(--muted-foreground)" };
}
