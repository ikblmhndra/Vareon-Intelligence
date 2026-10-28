import { cn } from "@/lib/utils";
import { GRADE_BADGE_CLASS } from "@/lib/intelligence/format";
import { gradeLines, type GradeFields } from "@/components/newsroom/score-reasons";

/** Chip nilai artikel (P6 bagian 6): kode Admiralty artikel + prioritas ("C1 · P131"), diwarnai
 * reliabilitas sumber. Artikel yang belum dinilai (`admiralty_code` null) tidak menampilkan chip.
 * Tooltip `title` berisi reliabilitas, kredibilitas + alasan, confidence, dan rincian prioritas. */
export function GradeChip({ a }: { a: GradeFields }) {
  if (!a.admiralty_code) return null;
  const label = a.priority_score != null ? `${a.admiralty_code} · P${a.priority_score}` : a.admiralty_code;
  return (
    <span
      title={gradeLines(a).join("\n")}
      className={cn(
        "inline-flex shrink-0 items-center rounded-full border px-1.5 font-code text-2xs leading-4",
        a.reliability_grade ? GRADE_BADGE_CLASS[a.reliability_grade] : "border-border text-muted-foreground",
      )}
    >
      {label}
    </span>
  );
}
