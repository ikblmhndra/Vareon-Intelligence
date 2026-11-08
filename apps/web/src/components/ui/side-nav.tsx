"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

interface SideNavProps {
  items: readonly { href: string; label: string }[];
  "aria-label": string;
  className?: string;
}

/** Navigasi samping antar-route (mis. Settings). Aktif = path diawali `href`. */
export function SideNav({ items, "aria-label": ariaLabel, className }: SideNavProps) {
  const pathname = usePathname();

  return (
    <nav aria-label={ariaLabel} className={cn("flex flex-col gap-0.5", className)}>
      {items.map((item) => {
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
      })}
    </nav>
  );
}
