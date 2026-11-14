import countries from "i18n-iso-countries";
import en from "i18n-iso-countries/langs/en.json";

countries.registerLocale(en);

// Kode non-ISO yang dipakai sumber berita (UK, EL) dipetakan ke ISO-3166 supaya namanya ketemu.
const ALIAS: Record<string, string> = { UK: "GB", EL: "GR" };

export const normalizeCountry = (code: string) => ALIAS[code.toUpperCase()] ?? code.toUpperCase();
export const countryName = (code: string) => countries.getName(normalizeCountry(code), "en") ?? code;
