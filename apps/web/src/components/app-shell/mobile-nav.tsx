"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { MenuIcon } from "lucide-react";

import { NAV_MORE, NAV_PRIMARY, isActive, type NavItem } from "@/components/app-shell/nav-items";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

/** Nav di bawah 1024 px: tombol "Menu" membuka `Sheet` berisi SEMUA tujuan (primer + More), jadi
 * tidak ada halaman yang hanya bisa dicapai dari desktop. Sheet ditutup saat link diklik karena
 * navigasi klien Next tidak me-remount layout. */
export function MobileNav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  const renderItem = (item: NavItem) => {
    const active = isActive(pathname, item);
    return (
      <li key={item.href}>
        <Link
          href={item.href}
          aria-current={active ? "page" : undefined}
          onClick={() => setOpen(false)}
          className={cn(
            "flex h-11 items-center rounded-[10px] border-l-2 px-3 text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            active
              ? "border-primary font-semibold text-foreground"
              : "border-transparent font-medium text-muted-foreground hover:bg-surface hover:text-foreground",
          )}
        >
          {item.label}
        </Link>
      </li>
    );
  };

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} aria-haspopup="dialog">
        <MenuIcon aria-hidden />
        Menu
      </Button>
      <Sheet open={open} onOpenChange={setOpen} title="Menu">
        <nav aria-label="Main">
          <ul className="flex flex-col gap-1">{NAV_PRIMARY.map(renderItem)}</ul>
          <hr className="my-3 border-border" />
          <ul className="flex flex-col gap-1">{NAV_MORE.map(renderItem)}</ul>
        </nav>
      </Sheet>
    </>
  );
}
