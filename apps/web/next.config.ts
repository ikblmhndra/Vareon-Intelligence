import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Build "standalone": `.next/standalone/server.js` + cuma node_modules yang
  // beneran dipakai (file tracing) -- image `web` (docker/web.Dockerfile)
  // jalan tanpa `pnpm install` penuh, jauh lebih kecil.
  output: "standalone",
  poweredByHeader: false,
  async headers() {
    // CSP penuh (script-src) dan HSTS sengaja belum dipasang: CSP butuh nonce untuk script inline
    // Next.js dan HSTS di host dengan sertifikat self-signed bisa mengunci pengguna keluar.
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
