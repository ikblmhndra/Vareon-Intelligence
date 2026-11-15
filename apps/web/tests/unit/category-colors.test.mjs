import { test } from "node:test";
import assert from "node:assert/strict";
import { categoryColorIndex, KNOWN_CATEGORY_SLOTS } from "../../src/lib/category-colors.ts";

test("known names ignore case and spacing", () => {
  assert.equal(categoryColorIndex("financial services"), categoryColorIndex("Financial Services "));
  assert.equal(categoryColorIndex("Data  Breach Article"), categoryColorIndex("data breach article"));
});
test("known names use the map, not the hash", () => {
  for (const [k, v] of Object.entries(KNOWN_CATEGORY_SLOTS)) assert.equal(categoryColorIndex(k), v);
});
test("unknown names are stable and in range", () => {
  const a = categoryColorIndex("Some New Sector");
  assert.equal(a, categoryColorIndex("Some New Sector"));
  assert.ok(Number.isInteger(a) && a >= 0 && a <= 9);
  assert.ok(categoryColorIndex("") >= 0);
});
test("news types never share a slot", () => {
  const types = ["global", "Security Technology & Best Practices", "Vendor Report Article",
    "Data Breach Article", "Tech Stack Article", "OT Article"];
  assert.equal(new Set(types.map(categoryColorIndex)).size, types.length);
});
