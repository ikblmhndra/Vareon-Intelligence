"use client";

import { Masthead } from "@/components/app-shell/masthead";
import { UtilityBar } from "@/components/app-shell/utility-bar";

/** Kolom shell selebar layar, dibatasi 1920 px termasuk gutter. Sebelumnya kolom dipaku 1328 px
 * (mockup 1440), sehingga layar lebar (~2000 px) banyak terbuang dan tabel lebar tidak muat.
 * Gutter 16 px di layar kecil, 40 px dari `lg:`. Dipakai header dan `<main>` supaya garis tinta dan
 * isi halaman sejajar persis. */
export const SHELL_COLUMN = "mx-auto w-full max-w-[1920px] px-4 lg:px-10";

/** Shell semua route ber-auth (pengganti sidebar sejak redesign FigCraft): utility bar, masthead,
 * lalu konten. Garis tinta di kedua bar sengaja selebar kolom (`SHELL_COLUMN`, maks 1920 px), bukan selebar layar. */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main-content"
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:top-3 focus-visible:left-3 focus-visible:z-50 focus-visible:rounded-full focus-visible:bg-primary focus-visible:px-4 focus-visible:py-2 focus-visible:text-sm focus-visible:font-medium focus-visible:text-primary-foreground focus-visible:shadow-md focus-visible:outline-none"
      >
        Skip to content
      </a>
      <header className={`${SHELL_COLUMN} print:hidden`}>
        <UtilityBar />
        <Masthead />
      </header>
      <main id="main-content" tabIndex={-1} className={`${SHELL_COLUMN} flex-1 pb-6 outline-none lg:pb-8`}>
        {children}
      </main>
    </div>
  );
}
