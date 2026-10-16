"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BotIcon,
  ClipboardListIcon,
  GaugeIcon,
  LayoutDashboardIcon,
  MailIcon,
  NewspaperIcon,
  RadarIcon,
  RadioTowerIcon,
  SettingsIcon,
  ShieldAlertIcon,
  type LucideIcon,
} from "lucide-react";

import { useAuth } from "@/components/providers/auth-provider";
import { BrandMark } from "@/components/brand-mark";
import { ChangelogDialog } from "@/components/changelog-dialog";
import { ClientSwitcher } from "@/components/client-switcher";
import { ThemeToggle } from "@/components/theme-toggle";
import { UserMenu } from "@/components/user-menu";
import { cn } from "@/lib/utils";

/** 9 route Fase 8 (docs/PROGRESS.md) -- padanan 8 tab lama + `/newsletter`
 * (route baru, gap yang ketemu pas survei). `/admin/users` di-guard
 * `role` di dalam `UserMenu`/halaman itu sendiri (bukan disembunyiin di
 * nav -- port perilaku lama: link tetep ada di DOM, cuma halamannya yang
 * nolak kalau bukan admin, lihat `deps.py::require_admin`).
 *
 * `/scrapers` (Fase 9, control plane scraper) -- keputusan user
 * (2026-09-25): halaman SENDIRI, bukan widget di `/dashboard` (yang
 * lama-nya "Scraper Health" numpang tab Dashboard). Read kebuka semua
 * user login (sama kayak halaman lain di nav ini), aksi tulis (trigger/
 * enable/disable/config) admin-only DI DALAM halaman-nya sendiri --
 * pola sama kayak `/admin/users` di atas, bukan disembunyiin dari nav. */
const NAV_ITEMS: readonly { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboardIcon },
  { href: "/newsroom", label: "Newsroom", icon: NewspaperIcon },
  { href: "/cve", label: "CVE Tracker", icon: ShieldAlertIcon },
  { href: "/intelligence", label: "Intelligence", icon: RadarIcon },
  { href: "/exec", label: "Exec", icon: GaugeIcon },
  { href: "/xintel", label: "X Intel", icon: RadioTowerIcon },
  { href: "/recap", label: "Recap", icon: ClipboardListIcon },
  { href: "/newsletter", label: "Newsletter", icon: MailIcon },
  { href: "/scrapers", label: "Scrapers", icon: BotIcon },
  { href: "/admin/users", label: "Admin", icon: SettingsIcon },
];

function Brand() {
  return (
    <Link
      href="/dashboard"
      className="flex items-center gap-3 rounded-full outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <BrandMark />
      <span className="font-heading text-lg leading-tight font-extrabold tracking-tight text-foreground">
        Vareon
        <br />
        Intelligence
      </span>
    </Link>
  );
}

function NavLinks({ orientation }: { orientation: "vertical" | "horizontal" }) {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Main"
      className={cn(orientation === "vertical" ? "flex flex-col gap-1" : "flex gap-1 overflow-x-auto")}
    >
      {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
        const active = pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex shrink-0 items-center gap-3 rounded-full px-4 text-sm outline-none transition-colors duration-200 focus-visible:ring-3 focus-visible:ring-ring/50",
              orientation === "vertical" ? "h-11" : "h-10",
              active
                ? "bg-primary font-semibold text-primary-foreground shadow-sm"
                : "font-medium text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Icon aria-hidden className="size-[18px]" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

/** Sidebar desktop (>= lg). Di bawah itu nav pindah ke `AppTopbar`. */
export function AppSidebar() {
  return (
    <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col gap-8 overflow-y-auto border-r border-border bg-background px-4 py-6 lg:flex">
      <div className="px-2">
        <Brand />
      </div>
      <NavLinks orientation="vertical" />
    </aside>
  );
}

/** Bar atas: aksi global (changelog, tema, client, user). Di layar kecil juga memuat brand + nav. */
export function AppTopbar() {
  const { user } = useAuth();
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background supports-[backdrop-filter]:bg-background/80 supports-[backdrop-filter]:backdrop-blur-md">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-8">
        <div className="lg:hidden">
          <Brand />
        </div>
        <div className="ml-auto flex items-center gap-2">
          <ChangelogDialog />
          <ThemeToggle />
          {user && <ClientSwitcher user={user} />}
          <UserMenu />
        </div>
      </div>
      <div className="px-4 pb-3 sm:px-8 lg:hidden">
        <NavLinks orientation="horizontal" />
      </div>
    </header>
  );
}
