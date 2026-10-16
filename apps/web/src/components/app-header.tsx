"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import {
  BotIcon,
  ClipboardListIcon,
  GaugeIcon,
  LayoutDashboardIcon,
  MailIcon,
  NewspaperIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { UserMenu } from "@/components/user-menu";
import { PLATFORM_NAME } from "@/lib/brand";
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

/** Preferensi sidebar ringkas (icon rail): opt-in, default tetap terbuka dengan label. Disimpan di
 * localStorage lewat `useSyncExternalStore` (bukan useState+useEffect: aturan lint
 * `react-hooks/set-state-in-effect`, dan server selalu merender "terbuka" jadi tak ada mismatch
 * hydration). `sidebarCollapsed` menjaga toggle tetap jalan di sesi ini walau localStorage diblokir. */
const SIDEBAR_KEY = "cti.sidebar.collapsed";
const sidebarListeners = new Set<() => void>();
let sidebarCollapsed: boolean | null = null;

function getSidebarCollapsed(): boolean {
  if (sidebarCollapsed === null) {
    try {
      sidebarCollapsed = window.localStorage.getItem(SIDEBAR_KEY) === "1";
    } catch {
      sidebarCollapsed = false;
    }
  }
  return sidebarCollapsed;
}

function setSidebarCollapsed(next: boolean) {
  sidebarCollapsed = next;
  try {
    window.localStorage.setItem(SIDEBAR_KEY, next ? "1" : "0");
  } catch {
    // Penyimpanan diblokir (mode privat): pilihan berlaku sampai tab ditutup.
  }
  sidebarListeners.forEach((notify) => notify());
}

function subscribeSidebar(onChange: () => void) {
  // Tab lain mengubah preferensi: buang cache supaya dibaca ulang dari localStorage.
  const onStorage = () => {
    sidebarCollapsed = null;
    onChange();
  };
  sidebarListeners.add(onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    sidebarListeners.delete(onChange);
    window.removeEventListener("storage", onStorage);
  };
}

function NavLinks({
  orientation,
  collapsed = false,
}: {
  orientation: "vertical" | "horizontal";
  /** Hanya berlaku untuk `vertical`: satu ikon per tujuan, label tetap ada di DOM (`sr-only`) + tooltip. */
  collapsed?: boolean;
}) {
  const pathname = usePathname();
  const rail = collapsed && orientation === "vertical";
  return (
    <nav
      id={orientation === "vertical" ? "app-sidebar-nav" : undefined}
      aria-label="Main"
      className={cn(orientation === "vertical" ? "flex flex-col gap-1" : "flex gap-1 overflow-x-auto")}
    >
      {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
        const active = pathname.startsWith(href);
        const className = cn(
          "flex shrink-0 items-center rounded-full text-sm outline-none transition-colors duration-200 focus-visible:ring-3 focus-visible:ring-ring/50",
          rail ? "size-11 justify-center" : "h-11 gap-3 px-4",
          active
            ? "bg-primary font-semibold text-primary-foreground shadow-sm"
            : "font-medium text-muted-foreground hover:bg-muted hover:text-foreground",
        );
        const content = (
          <>
            <Icon aria-hidden className="size-[18px]" />
            <span className={rail ? "sr-only" : undefined}>{label}</span>
          </>
        );
        if (!rail) {
          return (
            <Link key={href} href={href} aria-current={active ? "page" : undefined} className={className}>
              {content}
            </Link>
          );
        }
        return (
          <Tooltip key={href}>
            <TooltipTrigger
              render={<Link href={href} aria-current={active ? "page" : undefined} className={className} />}
            >
              {content}
            </TooltipTrigger>
            <TooltipContent side="right">{label}</TooltipContent>
          </Tooltip>
        );
      })}
    </nav>
  );
}

function SidebarToggle({ collapsed }: { collapsed: boolean }) {
  const label = collapsed ? "Expand sidebar" : "Collapse sidebar";
  const className = cn(
    "flex items-center rounded-full text-sm font-medium text-muted-foreground outline-none transition-colors duration-200 hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50",
    collapsed ? "size-11 justify-center" : "h-11 w-full gap-3 px-4",
  );
  const Icon = collapsed ? PanelLeftOpenIcon : PanelLeftCloseIcon;
  const content = (
    <>
      <Icon aria-hidden className="size-[18px]" />
      <span className={collapsed ? "sr-only" : undefined}>{label}</span>
    </>
  );
  const buttonProps = {
    type: "button" as const,
    onClick: () => setSidebarCollapsed(!collapsed),
    "aria-expanded": !collapsed,
    "aria-controls": "app-sidebar-nav",
    className,
  };
  if (!collapsed) return <button {...buttonProps}>{content}</button>;
  return (
    <Tooltip>
      <TooltipTrigger render={<button {...buttonProps} />}>{content}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}

/** Sidebar desktop (>= lg). Di bawah itu nav pindah ke `AppTopbar`. Bisa diciutkan jadi icon rail 72px. */
export function AppSidebar() {
  const collapsed = useSyncExternalStore(subscribeSidebar, getSidebarCollapsed, () => false);
  return (
    <aside
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 flex-col gap-8 overflow-y-auto border-r border-border bg-background py-6 lg:flex",
        collapsed ? "w-[72px] items-center px-3" : "w-64 px-4",
      )}
    >
      {collapsed ? (
        <Link
          href="/dashboard"
          aria-label={PLATFORM_NAME}
          className="rounded-full outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <BrandMark />
        </Link>
      ) : (
        <div className="px-2">
          <Brand />
        </div>
      )}
      <NavLinks orientation="vertical" collapsed={collapsed} />
      <div className={cn("mt-auto", !collapsed && "w-full")}>
        <SidebarToggle collapsed={collapsed} />
      </div>
    </aside>
  );
}

/** Bar atas: aksi global (changelog, tema, client, user). Di layar kecil juga memuat brand + nav. */
export function AppTopbar() {
  const { user } = useAuth();
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background">
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
