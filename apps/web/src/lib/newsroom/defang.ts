const SCHEMES: Record<string, string> = { http: "hxxp", https: "hxxps", ftp: "fxp" };

/**
 * Defang indikator untuk tampilan (bukan untuk salin: tombol copy memakai nilai asli). Skema
 * http/https/ftp jadi hxxp/hxxps/fxp, setiap titik di host dan IPv4 jadi `[.]`, `@` jadi `[@]`, dan
 * `:` sebelum port jadi `[:]`; path/query dibiarkan supaya tetap terbaca. IPv6 (lebih dari satu
 * titik dua) dibiarkan karena tidak berisi titik dan bukan target klik yang berbahaya.
 */
export function defang(value: string): string {
  let scheme = "";
  let rest = value;
  const m = /^([a-z]+):\/\/(.*)$/i.exec(value);
  if (m && SCHEMES[m[1].toLowerCase()]) {
    scheme = `${SCHEMES[m[1].toLowerCase()]}://`;
    rest = m[2];
  }
  const cut = rest.search(/[/?#]/);
  const authority = cut === -1 ? rest : rest.slice(0, cut);
  const tail = cut === -1 ? "" : rest.slice(cut);
  const colons = (authority.match(/:/g) ?? []).length;
  if (authority.startsWith("[") || colons > 1) return scheme + authority + tail;
  const safe = authority
    .replace(/\./g, "[.]")
    .replace(/@/g, "[@]")
    .replace(/:(\d+)$/, "[:]$1");
  return scheme + safe + tail;
}
