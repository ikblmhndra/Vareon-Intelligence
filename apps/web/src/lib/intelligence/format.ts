/** Admiralty reliability grade -> warna badge. A/B baik (hijau/biru),
 * C/D sedang (kuning/oranye), E/F buruk (merah/abu), niru urutan
 * `_RELIABILITY_ORDER` (`source_score.py`) tapi di-mapping ke token
 * Tailwind, bukan warna literal legacy. */
export const GRADE_BADGE_CLASS: Record<string, string> = {
  A: "text-success border-success/40",
  B: "text-primary border-primary/40",
  C: "text-warning border-warning/40",
  D: "text-warning border-warning/40",
  E: "text-destructive border-destructive/40",
  F: "text-muted-foreground border-border",
};

type Tone = "destructive" | "warning" | "info" | "neutral";

/** ID tampilan PIR/RFI berpad dua digit ("PIR-03"); ID database tetap angka biasa. */
export function displayId(prefix: "PIR" | "RFI", id: number): string {
  return `${prefix}-${String(id).padStart(2, "0")}`;
}

/** Prioritas tersimpan (P1..P3) -> kata + nada. Nilai tak dikenal ditampilkan apa adanya, netral. */
export function pirPriority(p: string): { label: string; tone: Tone } {
  if (p === "P1") return { label: "Critical", tone: "destructive" };
  if (p === "P2") return { label: "High", tone: "warning" };
  if (p === "P3") return { label: "Medium", tone: "info" };
  return { label: p, tone: "neutral" };
}

export const PIR_PRIORITY_OPTIONS = [
  { value: "P1", label: "Critical" },
  { value: "P2", label: "High" },
  { value: "P3", label: "Medium" },
] as const;

/** Skor keyakinan 0-100 -> kata; `null` = belum dinilai (jangan dibaca sebagai "low"). */
export function confidenceWord(n: number | null): "high" | "medium" | "low" | "unrated" {
  if (n === null) return "unrated";
  if (n >= 80) return "high";
  if (n >= 50) return "medium";
  return "low";
}

/** Asal entri: `default` = dibuat otomatis oleh pipeline, bukan analis. */
export function originLabel(o: string): string {
  return o === "default" ? "auto" : o === "analyst" ? "analyst" : o;
}

const ACTIONS = {
  block_now: { word: "BLOCK", tone: "destructive" },
  investigate: { word: "INVESTIGATE", tone: "warning" },
  monitor: { word: "MONITOR", tone: "info" },
  archive: { word: "ARCHIVE", tone: "neutral" },
} as const;

/** Label aksi IOC dari backend -> kata kapital + nada; `null` bila kosong atau tak dikenal. */
export function actionLabel(
  label: string | null,
): { word: "BLOCK" | "INVESTIGATE" | "MONITOR" | "ARCHIVE"; tone: Tone } | null {
  if (!label || !Object.hasOwn(ACTIONS, label)) return null;
  return ACTIONS[label as keyof typeof ACTIONS];
}
