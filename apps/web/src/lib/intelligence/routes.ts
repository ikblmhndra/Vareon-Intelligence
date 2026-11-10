export interface IntelligenceRoute {
  segment: string;
  href: string;
  /** H1 halaman. */
  title: string;
  description: string;
  /** Judul tab browser (sama dengan `metadata.title` di layout segmen). */
  docTitle: string;
}

/** Tabel rute Intelligence: sumber tunggal H1, deskripsi, dan urutan pil. Teks diambil verbatim dari inventaris
 * desain 2b supaya header, pil, dan judul tab tidak bisa saling menyimpang. */
export const INTELLIGENCE_ROUTES: readonly IntelligenceRoute[] = [
  {
    segment: "risk-matrix",
    href: "/intelligence/risk-matrix",
    title: "Risk matrix",
    description:
      "Where threat activity concentrates, by victim industry and country, compared with the previous period",
    docTitle: "Risk matrix",
  },
  {
    segment: "source-reliability",
    href: "/intelligence/source-reliability",
    title: "Source reliability",
    description:
      "Admiralty grading for every source the scrapers read: how reliable the source is, how credible its reporting",
    docTitle: "Source reliability",
  },
  {
    segment: "early-warning",
    href: "/intelligence/early-warning",
    title: "Early warning",
    description: "Entities whose reporting in the last 7 days is far above their own baseline",
    docTitle: "Early warning",
  },
  {
    segment: "pir",
    href: "/intelligence/pir",
    title: "Priority intelligence requirements",
    description: "What leadership needs to know, and whether incoming reporting is covering it",
    docTitle: "PIR",
  },
  {
    segment: "rfi",
    href: "/intelligence/rfi",
    title: "Requests for information",
    description: "Specific questions from stakeholders, tracked to an answer",
    docTitle: "RFI",
  },
  {
    segment: "mitre",
    href: "/intelligence/mitre",
    title: "MITRE ATT&CK heatmap",
    description:
      "Which techniques each threat actor is reported using; click a cell for the articles behind it",
    docTitle: "MITRE ATT&CK heatmap",
  },
  {
    segment: "entities",
    href: "/intelligence/entities",
    title: "Entities",
    description: "Every threat actor, malware, technique, sector and place the pipeline has named",
    docTitle: "Entities",
  },
  {
    segment: "ioc-management",
    href: "/intelligence/ioc-management",
    title: "IOC management",
    description:
      "Indicators extracted from articles, scored for confidence and actionability, with analyst feedback",
    docTitle: "IOC management",
  },
  {
    segment: "campaign-clusters",
    href: "/intelligence/campaign-clusters",
    title: "Campaign clusters",
    description: "Articles grouped into campaigns by shared actors, techniques, IOCs and CVEs",
    docTitle: "Campaign clusters",
  },
];

/** Rute untuk `pathname`; `null` untuk detail entitas (`/intelligence/entities/{id}`, halaman itu punya `<h1>`
 * sendiri) dan untuk path di luar tabel. `/intelligence/entities/resolve` tetap memakai header Entities. */
export function routeFor(pathname: string): IntelligenceRoute | null {
  const parts = pathname.split("/").filter(Boolean);
  if (parts[0] !== "intelligence" || parts.length < 2) return null;
  const segment = parts[1];
  if (segment === "entities" && parts.length > 2 && parts[2] !== "resolve") return null;
  return INTELLIGENCE_ROUTES.find((r) => r.segment === segment) ?? null;
}
