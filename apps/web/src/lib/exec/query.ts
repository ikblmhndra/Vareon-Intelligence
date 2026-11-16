/** Status HTTP yang dibawa galat query Exec (`new Error(msg, { cause: status })`), atau null bila bukan galat HTTP. */
export function errorStatus(e: unknown): number | null {
  const cause = e instanceof Error ? e.cause : null;
  return typeof cause === "number" ? cause : null;
}

/** 4xx (izin/validasi) tidak akan sembuh dengan diulang: react-query jangan retry. Dipakai `retry` query dashboard dan brief. */
export function isClientError(e: unknown): boolean {
  const s = errorStatus(e);
  return s !== null && s >= 400 && s < 500;
}
