/** Label manusiawi untuk nilai enum mentah (tipe IOC, reliabilitas sumber). Tanpa import. */

const ACRONYMS: Record<string, string> = {
  url: "URL", ip: "IP", ipv4: "IPv4", ipv6: "IPv6", cidr: "CIDR", asn: "ASN", dns: "DNS",
  md5: "MD5", sha1: "SHA1", sha256: "SHA256", sha512: "SHA512", cve: "CVE", kev: "KEV",
  ttp: "TTP", ot: "OT", it: "IT", api: "API", ssl: "SSL", tls: "TLS", id: "ID",
};

/** `url_with_path` -> "URL with path". String tanpa `_` yang bukan huruf besar semua dikembalikan apa adanya,
 * kecuali satu kata akronim dikenal (`ipv4` -> "IPv4", `sha256` -> "SHA256"). */
export function enumLabel(raw: string): string {
  if (!raw) return "";
  const isScreaming = raw === raw.toUpperCase();
  if (!raw.includes("_") && !isScreaming) return ACRONYMS[raw.toLowerCase()] ?? raw;
  const words = raw.split("_").filter(Boolean).map((w) => w.toLowerCase());
  return words
    .map((w, i) => {
      const acr = ACRONYMS[w];
      if (acr) return acr;
      return i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w;
    })
    .join(" ");
}

/** `enumLabel` dengan huruf pertama dibesarkan (`domain` -> "Domain"), untuk chip bergaya kalimat. */
export function sentenceLabel(raw: string): string {
  const l = enumLabel(raw);
  return l.charAt(0).toUpperCase() + l.slice(1);
}
