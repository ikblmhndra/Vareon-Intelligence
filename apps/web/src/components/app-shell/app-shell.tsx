"use client";

import { Masthead } from "@/components/app-shell/masthead";
import { UtilityBar } from "@/components/app-shell/utility-bar";

/** Kolom shell mockup: konten 1328 px di tengah (halaman 1440 = 56 px tiap sisi), padding sempit di
 * bawah 1440. Dipakai header dan `<main>` supaya garis tinta dan isi halaman sejajar persis. */
export const SHELL_COLUMN = "mx-auto w-full max-w-[1328px] px-4 lg:px-8 min-[1440px]:px-0";

/** Shell semua route ber-auth (pengganti sidebar sejak redesign FigCraft): utility bar, masthead,
 * lalu konten. Garis tinta di kedua bar sengaja selebar kolom, bukan selebar layar (node Utility
 * dan Masthead di mockup = 1328 px). */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main-content"
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:top-3 focus-visible:left-3 focus-visible:z-50 focus-visible:rounded-full focus-visible:bg-primary focus-visible:px-4 focus-visible:py-2 focus-visible:text-sm focus-visible:font-medium focus-visible:text-primary-foreground focus-visible:shadow-md focus-visible:outline-none"
      >
        Skip to content
      </a>
      <header className={SHELL_COLUMN}>
        <UtilityBar />
        <Masthead />
      </header>
      <main id="main-content" tabIndex={-1} className={`${SHELL_COLUMN} flex-1 py-6 outline-none lg:py-8`}>
        {children}
      </main>
    </div>
  );
}
