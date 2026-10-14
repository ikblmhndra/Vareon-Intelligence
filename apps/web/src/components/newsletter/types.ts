import type { components } from "@/lib/api/schema";

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
  warnings: [],
  metadataTitles: [],
};
