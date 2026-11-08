"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDownIcon } from "lucide-react";

import { MobileNav } from "@/components/app-shell/mobile-nav";
import { NAV_MORE, NAV_PRIMARY, isActive } from "@/components/app-shell/nav-items";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

const FOCUS =
  "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/** Label nav + garis aktif 2x24 px merah DI BAWAH label (mockup: kolom vertikal, gap 6). Garis
 * transparan tetap dirender saat tidak aktif supaya tinggi item sama dan baris nav tidak loncat. */
function NavLabel({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <>
      <span className="flex items-center gap-1">{children}</span>
      <span aria-hidden className={cn("h-0.5 w-6", active ? "bg-primary" : "bg-transparent")} />
    </>
  );
}

const ITEM =
  "flex flex-col items-center gap-1.5 rounded-sm text-[13px] font-semibold whitespace-nowrap transition-colors";

/** Masthead editorial (mockup FigCraft): wordmark "Vareon" + titik merah di kiri, nav di kanan
 * rata bawah. Nav penuh dari `lg:` (1024 px); di bawahnya diganti tombol "Menu" (`MobileNav`). */
export function Masthead() {
  const pathname = usePathname();
  const moreActive = NAV_MORE.some((item) => isActive(pathname, item));

  return (
    <div className="flex items-end justify-between gap-6 border-b border-foreground pt-[18px] pb-3.5">
      <Link
        href="/dashboard"
        className={cn("flex items-end gap-1 rounded-sm text-foreground", FOCUS)}
      >
        <span className="font-heading text-[46px] leading-[58px] font-bold tracking-[-0.026em]">
          Vareon
        </span>
        <span aria-hidden className="mb-2 size-2.5 rounded-full bg-primary" />
      </Link>

      <nav aria-label="Main" className="hidden items-end gap-6 pb-2 lg:flex">
        {NAV_PRIMARY.map((item) => {
          const active = isActive(pathname, item);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                ITEM,
                FOCUS,
                active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <NavLabel active={active}>{item.label}</NavLabel>
            </Link>
          );
        })}
        <DropdownMenu>
          <DropdownMenuTrigger
            className={cn(
              ITEM,
              FOCUS,
              "cursor-pointer",
              moreActive ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <NavLabel active={moreActive}>
              More
              <ChevronDownIcon aria-hidden className="size-3.5" />
            </NavLabel>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            {NAV_MORE.map((item) => {
              const active = isActive(pathname, item);
              return (
                <DropdownMenuItem
                  key={item.href}
                  render={<Link href={item.href} aria-current={active ? "page" : undefined} />}
                  className={cn(active && "font-semibold text-foreground")}
                >
                  {item.label}
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      </nav>

      <div className="lg:hidden">
        <MobileNav />
      </div>
    </div>
  );
}
