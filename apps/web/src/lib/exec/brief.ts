import type { components } from "@/lib/api/schema";

type ExecBriefFilters = components["schemas"]["ExecBriefFilters"];

export interface BriefFinding {
  title: string;
  detail: string;
}

export interface ParsedBrief {
  headline: string;
  paragraph: string;
  findings: BriefFinding[];
  otherSections: string[];
}

/** "Last 30 days · threat news only · confirmed only" (spec 6.3). */
export function briefFiltersLabel(f: ExecBriefFilters): string {
  return `Last ${f.days} days · ${f.incident_only ? "threat news only" : "all articles"}${f.confirmed_only ? " · confirmed only" : ""}`;
}

/** Buang penanda Markdown inline supaya aman jadi teks polos (judul/headline). */
function stripInline(s: string): string {
  return s
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*_`]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

// Akhir kalimat: . ! ? (boleh diikuti ** penutup tebal) lalu spasi + huruf kapital, atau akhir teks.
const SENTENCE_END = /[.!?]\**(?=\s+[A-Z]|\s*$)/;

/** [kalimat pertama, sisanya]. Tanpa batas kalimat: seluruh teks jadi kalimat pertama. */
function splitFirstSentence(text: string): [string, string] {
  const flat = text.trim();
  const m = SENTENCE_END.exec(flat);
  if (!m) return [flat, ""];
  const end = m.index + m[0].length;
  return [flat.slice(0, end), flat.slice(end).trim()];
}

const ITEM = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/;

function parseItem(raw: string): BriefFinding | null {
  const bold = /^\*\*([\s\S]+?)\*\*\s*([\s\S]*)$/.exec(raw);
  let title: string;
  let detail: string;
  if (bold) {
    title = bold[1];
    detail = bold[2].replace(/^[:\-–—]\s*/, "");
  } else {
    [title, detail] = splitFirstSentence(raw);
  }
  title = stripInline(title).replace(/[.:]$/, "");
  return title ? { title, detail: detail.trim() } : null;
}

function parseFindings(body: string): BriefFinding[] {
  const items: string[] = [];
  let open = false;
  for (const line of body.split("\n")) {
    const m = ITEM.exec(line);
    if (m) {
      items.push(m[1].trim());
      open = true;
    } else if (!line.trim()) {
      open = false;
    } else if (open) {
      items[items.length - 1] += ` ${line.trim()}`;
    } else {
      // Baris tanpa penanda daftar: tetap diperlakukan sebagai butir, supaya teks tidak hilang.
      items.push(line.trim());
      open = true;
    }
  }
  return items.map(parseItem).filter((f): f is BriefFinding => f !== null);
}

/** Pecah Markdown brief (5 section `##` dari prompt LLM) jadi bagian kartu. `null` bila tidak ada section
 * "Executive Summary" atau headline-nya kosong; pemanggil lalu menampilkan Markdown mentah (tidak ada teks hilang). */
export function parseBrief(markdown: string): ParsedBrief | null {
  const sections: { name: string; body: string }[] = [];
  for (const line of markdown.split("\n")) {
    const h = /^##\s+(.*)$/.exec(line);
    if (h) sections.push({ name: h[1].trim(), body: "" });
    else if (sections.length) sections[sections.length - 1].body += `${line}\n`;
  }
  const norm = (n: string) => n.toLowerCase().replace(/[*:\s]+$/g, "");
  const exec = sections.find((s) => norm(s.name).startsWith("executive summary"));
  if (!exec) return null;
  const [first, rest] = splitFirstSentence(exec.body);
  const headline = stripInline(first);
  if (!headline) return null;
  const findingsSection = sections.find((s) => norm(s.name).startsWith("key findings"));
  return {
    headline,
    paragraph: rest,
    findings: findingsSection ? parseFindings(findingsSection.body) : [],
    otherSections: sections.filter((s) => s !== exec && s !== findingsSection && s.name && s.body.trim()).map((s) => s.name),
  };
}

// Self-check dev-only (tidak ada test runner di web): tiga masukan nyata dari brief Task 12.
if (process.env.NODE_ENV === "development") {
  const full = parseBrief(
    "## Executive Summary\nRansomware activity rose 40%. Healthcare was hit hardest. Patch now.\n\n## Key Findings & Recommendations\n- **LockBit returns.** New leak site seen.\n- **Patch Citrix.** Exploited in the wild.\n\n## Threat Landscape\nText\n## Outlook\nText\n",
  );
  console.assert(full?.headline === "Ransomware activity rose 40%.", "brief: headline");
  console.assert(full?.paragraph === "Healthcare was hit hardest. Patch now.", "brief: paragraph");
  console.assert(full?.findings[0].title === "LockBit returns" && full.findings[0].detail === "New leak site seen.", "brief: **Title.** detail");
  console.assert(full?.otherSections.join("|") === "Threat Landscape|Outlook", "brief: other sections");
  const plain = parseBrief("## Executive Summary\nOne sentence only.\n## Key Findings\n- Plain bullet one. More detail.\n* Second\n1. Third item.");
  console.assert(plain?.paragraph === "", "brief: one sentence -> empty paragraph");
  console.assert(plain?.findings.length === 3 && plain.findings[0].title === "Plain bullet one" && plain.findings[0].detail === "More detail.", "brief: plain bullets");
  console.assert(parseBrief("Just some text\nwithout headings") === null, "brief: no headings -> null (fallback)");
}
