"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useId } from "react";

import { cn } from "@/lib/utils";

type Item = { href: string; label: string };
type Group = { heading: string; items: readonly Item[] };

type SideNavProps = {
  "aria-label": string;
  className?: string;
} & (
  | { items: readonly Item[]; groups?: never }
  | { groups: readonly Group[]; items?: never }
);

/** Navigasi samping antar-route (mis. Settings). Aktif = path diawali `href`.
 * `groups` = daftar bertajuk (mis. Admin); grup tanpa item tidak dirender. */
export function SideNav({ items, groups, "aria-label": ariaLabel, className }: SideNavProps) {
  const pathname = usePathname();
  const baseId = useId();

  const links = (list: readonly Item[]) =>
    list.map((item) => {
      const active = pathname.startsWith(item.href);
      return (
        <Link
          key={item.href}
          href={item.href}
          aria-current={active ? "page" : undefined}
          className={cn(
            "rounded-[8px] px-3 py-2 text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            active
              ? "bg-surface font-semibold text-foreground"
              : "text-muted-foreground hover:bg-surface hover:text-foreground",
          )}
        >
          {item.label}
        </Link>
      );
    });

  return (
    <nav
      aria-label={ariaLabel}
      className={cn("flex flex-col", groups ? "gap-4" : "gap-0.5", className)}
    >
      {groups
        ? groups
            .filter((g) => g.items.length > 0)
            .map((g, i) => (
              <div key={g.heading} className="flex flex-col gap-0.5">
                <h2
                  id={`${baseId}-${i}`}
                  className="px-3 pb-1 text-2xs font-semibold tracking-wide text-muted-foreground uppercase"
                >
                  {g.heading}
                </h2>
                <ul aria-labelledby={`${baseId}-${i}`} className="flex flex-col gap-0.5">
                  {g.items.map((item) => (
                    <li key={item.href} className="flex flex-col">
                      {links([item])}
                    </li>
                  ))}
                </ul>
              </div>
            ))
        : links(items)}
    </nav>
  );
}
