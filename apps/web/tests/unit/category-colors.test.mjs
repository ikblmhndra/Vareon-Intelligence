import { test } from "node:test";
import assert from "node:assert/strict";
import { assignCategorySlots, categoryColorIndex, KNOWN_CATEGORY_SLOTS } from "../../src/lib/category-colors.ts";

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
    "Data Breach Article", "Tech Stack Article", "OT Article", "Zero Day Article",
    "Unrelated Tech Stack Article", "apac", "Unknown"];
  assert.equal(new Set(types.map(categoryColorIndex)).size, types.length);
});
test("prototype keys do not leak into the lookup", () => {
  for (const k of ["constructor", "__proto__", "toString"]) {
    const i = categoryColorIndex(k);
    assert.ok(Number.isInteger(i) && i >= 0 && i <= 9, k);
  }
});
test("assignCategorySlots gives 8 countries 8 distinct slots", () => {
  const names = ["China", "India", "North Korea", "Ukraine", "Russia", "Germany", "France", "Indonesia"];
  assert.equal(new Set(assignCategorySlots(names)).size, 8);
});
test("assignCategorySlots keeps mapped names on their slot", () => {
  const names = ["Global", "OT Article", "Foo", "Bar"];
  const out = assignCategorySlots(names);
  assert.equal(out[0], categoryColorIndex("Global"));
  assert.equal(out[1], categoryColorIndex("OT Article"));
  assert.equal(new Set(out).size, 4);
});
test("assignCategorySlots is deterministic and bounded for >10 names", () => {
  const names = Array.from({ length: 11 }, (_, i) => `name-${i}`);
  const a = assignCategorySlots(names);
  assert.deepEqual(a, assignCategorySlots(names));
  assert.equal(a.length, 11);
  assert.ok(a.every((v) => Number.isInteger(v) && v >= 0 && v <= 9));
});
