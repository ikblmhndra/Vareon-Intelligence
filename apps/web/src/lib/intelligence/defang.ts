/** Tampilan saja: bentuk defanged supaya IOC tidak bisa diklik/dieksekusi tanpa sengaja.
 * Nilai kanonik (API, ekspor STIX, lookup) tidak pernah diubah. Hash tidak diubah. */
export function defang(type: string, value: string): string {
  switch (type) {
    case "ip":
    case "domain":
      return value.replace(/\./g, "[.]");
    case "email":
      return value.replace(/@/g, "[@]").replace(/\./g, "[.]");
    case "url":
    case "url_with_path":
      return value.replace(/^http/i, (m) => (m === m.toLowerCase() ? "hxxp" : "HXXP")).replace(/\./g, "[.]");
    default:
      return value;
  }
}
