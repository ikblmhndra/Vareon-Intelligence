import { GlobeIcon, MapPinIcon, StarIcon, TargetIcon } from "lucide-react";

import type { SectionName } from "@/lib/newsletter/composer";

const ICONS = {
  highlights: StarIcon,
  apac: MapPinIcon,
  global_news: GlobeIcon,
  indonesia: TargetIcon,
} as const;

export function SectionIcon({ section, className }: { section: "highlights" | SectionName; className?: string }) {
  const Icon = ICONS[section];
  return <Icon aria-hidden className={className} />;
}
