interface LegendRowProps {
  items: readonly { label: string; swatchClass: string }[];
}

/** Legenda satu baris: kotak warna (dekoratif, `aria-hidden`) + label teks, jadi warna tak jadi satu-satunya
 * pembawa makna. `swatchClass` = kelas latar token tema (mis. `bg-destructive`). */
export function LegendRow({ items }: LegendRowProps) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-muted-foreground">
      {items.map((item) => (
        <li key={item.label} className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className={`size-2.5 rounded-[3px] ${item.swatchClass}`} />
          {item.label}
        </li>
      ))}
    </ul>
  );
}
