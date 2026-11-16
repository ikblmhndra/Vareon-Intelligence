import { test } from "node:test";
import assert from "node:assert/strict";
import { shortTickLabel } from "../../src/lib/chart-ticks.ts";

test("ISO day -> '8 Nov'", () => assert.equal(shortTickLabel("2026-11-08"), "8 Nov"));
test("ISO month -> 'Mar 2026'", () => assert.equal(shortTickLabel("2026-03"), "Mar 2026"));
test("other labels pass through", () => {
  assert.equal(shortTickLabel("Financial Services"), "Financial Services");
  assert.equal(shortTickLabel("2026-13-40"), "2026-13-40");
});
