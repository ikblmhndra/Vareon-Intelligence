import { test } from "node:test";
import assert from "node:assert/strict";
import { pageWindow, parseStoredPageSize } from "../../src/lib/page-size.ts";

const OPTS = [10, 25, 50, 100];

test("accepts a stored size that is an option", () => {
  assert.equal(parseStoredPageSize("50", OPTS, 25), 50);
  assert.equal(parseStoredPageSize(" 100 ", OPTS, 25), 100);
});
test("falls back on missing, junk or out-of-list values", () => {
  assert.equal(parseStoredPageSize(null, OPTS, 25), 25);
  assert.equal(parseStoredPageSize("", OPTS, 25), 25);
  assert.equal(parseStoredPageSize("abc", OPTS, 25), 25);
  assert.equal(parseStoredPageSize("-10", OPTS, 25), 25);
  assert.equal(parseStoredPageSize("30", OPTS, 25), 25);
  assert.equal(parseStoredPageSize("25.5", OPTS, 25), 25);
});

test("pageWindow slices a page and clamps out-of-range pages", () => {
  assert.deepEqual(pageWindow(1300, 1, 25), { page: 1, totalPages: 52, start: 0, end: 25 });
  assert.deepEqual(pageWindow(1300, 52, 25), { page: 52, totalPages: 52, start: 1275, end: 1300 });
  assert.deepEqual(pageWindow(30, 9, 25), { page: 2, totalPages: 2, start: 25, end: 30 });
  assert.deepEqual(pageWindow(0, 3, 25), { page: 1, totalPages: 1, start: 0, end: 0 });
  assert.deepEqual(pageWindow(10, 0, 25), { page: 1, totalPages: 1, start: 0, end: 10 });
});
