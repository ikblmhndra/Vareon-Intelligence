import type { Metadata } from "next";
import { Google_Sans_Flex, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

import { AuthProvider } from "@/components/providers/auth-provider";
import { QueryProvider } from "@/components/providers/query-provider";
import { ThemeProvider } from "@/components/providers/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { PLATFORM_NAME } from "@/lib/brand";

// Brand font (roadmap #1): Google Sans Flex variabel untuk UI + heading;
// IBM Plex Mono tetap untuk data/IOC/hash supaya karakter ambigu terbaca. Dipakai lewat kelas
// `font-code` (BUKAN `font-mono`: token itu di tema = Google Sans Flex, proporsional). Pakai
// `font-code` untuk nilai data (IOC, hash, IP, CVE/TTP ID, jadwal cron); bobot 400/500/600.
const googleSansFlex = Google_Sans_Flex({
  variable: "--font-google-sans-flex",
  subsets: ["latin"],
});

const ibmPlexMono = IBM_Plex_Mono({
  variable: "--font-ibm-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  // Segmen route mengisi `%s` lewat `metadata.title` mereka, jadi tab browser membedakan halaman.
  title: { default: PLATFORM_NAME, template: `%s · ${PLATFORM_NAME}` },
  description: "Cyber threat intelligence platform",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${googleSansFlex.variable} ${ibmPlexMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col font-sans">
        <ThemeProvider>
          <QueryProvider>
            <AuthProvider>
              <TooltipProvider>{children}</TooltipProvider>
            </AuthProvider>
          </QueryProvider>
          <Toaster richColors position="top-right" />
        </ThemeProvider>
      </body>
    </html>
  );
}
