const SCHEMES: Record<string, string> = { http: "hxxp", https: "hxxps", ftp: "fxp" };

/** IPv6 sungguhan: dikurung `[...]`, memuat `::`, atau hanya heksadesimal dan titik dua dengan
 * minimal dua `:`. `host:port` dan `user:pass@host:80` bukan IPv6 walau titik duanya lebih dari satu. */
function isIPv6(authority: string): boolean {
  return (
    authority.startsWith("[") ||
    authority.includes("::") ||
    (/^[0-9a-f:]+$/i.test(authority) && (authority.match(/:/g) ?? []).length > 1)
  );
}

/**
 * Defang indikator untuk tampilan (bukan untuk salin: tombol copy memakai nilai asli). Skema
 * http/https/ftp jadi hxxp/hxxps/fxp (skema lain dipertahankan), setiap titik di host dan IPv4 jadi
 * `[.]`, `@` jadi `[@]`, dan `:` sebelum port jadi `[:]`; path/query dibiarkan supaya tetap
 * terbaca. Userinfo dipisah di `@` terakhir sebelum host/port diproses. IPv6 sungguhan dibiarkan
 * karena tidak berisi titik dan bukan target klik yang berbahaya.
 */
export function defang(value: string): string {
  let scheme = "";
  let rest = value;
  const m = /^([a-z][a-z0-9+.-]*):\/\/(.*)$/i.exec(value);
  if (m) {
    scheme = `${SCHEMES[m[1].toLowerCase()] ?? m[1]}://`;
    rest = m[2];
  }
  const cut = rest.search(/[/?#]/);
  const authority = cut === -1 ? rest : rest.slice(0, cut);
  const tail = cut === -1 ? "" : rest.slice(cut);
  const at = authority.lastIndexOf("@");
  const userinfo = at === -1 ? "" : authority.slice(0, at);
  const host = at === -1 ? authority : authority.slice(at + 1);
  const user = userinfo.replace(/\./g, "[.]");
  const sep = at === -1 ? "" : "[@]";
  if (isIPv6(host)) return scheme + user + sep + host + tail;
  const safeHost = host.replace(/\./g, "[.]").replace(/:(\d+)$/, "[:]$1");
  return scheme + user + sep + safeHost + tail;
}
