import { test } from "node:test";
import assert from "node:assert/strict";
import { parseStoredPageSize } from "../../src/lib/page-size.ts";

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
