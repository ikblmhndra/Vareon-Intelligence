import type { components } from "@/lib/api/schema";
import type { SectionName, SlotKey } from "@/lib/newsletter/composer";

type NewsletterSectionsBody = components["schemas"]["NewsletterSectionsBody"];

/** Isi bagian "Customize Template". Intro (`customIntro`) diedit di blok Executive Summary, bukan
 * di panel template: itu field yang SAMA (`custom_intro`), yang dirender template email sebagai
 * Executive Summary. */
export interface TemplateState {
  customCss: string;
  customIntro: string;
  customFooter: string;
  includeClusters: boolean;
  clusterDays: number;
}

export const DEFAULT_TEMPLATE_STATE: TemplateState = {
  customCss: "",
  customIntro: "",
  customFooter: "",
  includeClusters: false,
  clusterDays: 7,
};

export type SummaryLanguage = "id" | "en";

export interface PreviewDialogState {
  open: boolean;
  /** Label edisi ("October 2026" atau "Week N, YYYY" untuk baris lama); kosong sebelum ada jawaban. */
  label: string;
  html: string | null;
  mode: "compose" | "saved";
  /** Tombol header yang membuka dialog: "Preview" (hanya melihat) atau "Generate edition" (menuju draft). */
  origin: "preview" | "generate";
  savedId?: number;
  /** Request yang baru di-preview. Draft dibuat dari PERSIS ini, bukan dari composer yang bisa saja
   * sudah berubah, jadi yang dibuat = yang barusan dilihat analis. */
  body?: NewsletterSectionsBody;
  /** Peringatan yang membuat tombol draft berubah jadi "anyway": ukuran email dan penanda CVE. */
  warnings: string[];
  /** Judul kartu yang ringkasannya ditulis dari metadata saja (informasi, bukan peringatan). */
  metadataTitles: string[];
}

export const PREVIEW_DIALOG_CLOSED: PreviewDialogState = {
  open: false,
  label: "",
  html: null,
  mode: "compose",
  origin: "preview",
  warnings: [],
  metadataTitles: [],
};

/** Blok yang bisa dipilih di kolom Template. Empat pertama = bagian berisi artikel; tiga terakhir
 * = bagian lain email (ringkasan eksekutif, klaster kampanye, footer dan CSS). */
export type BlockId = "highlights" | "indonesia" | "apac" | "global_news" | "summary" | "clusters" | "footer";

/** Urutan di kolom Template (Indonesia di depan APAC dan Global, urutan prioritas pembaca), beda
 * dari urutan section di email (`SECTIONS`). `compact` null = Highlights tak punya baris Also Noted. */
export const SECTION_BLOCKS: { id: "highlights" | SectionName; title: string; full: SlotKey; compact: SlotKey | null }[] = [
  { id: "highlights", title: "Highlights", full: "highlights", compact: null },
  { id: "indonesia", title: "Indonesia", full: "indonesia_full", compact: "indonesia_compact" },
  { id: "apac", title: "Asia Pacific", full: "apac_full", compact: "apac_compact" },
  { id: "global_news", title: "Global", full: "global_news_full", compact: "global_news_compact" },
];
