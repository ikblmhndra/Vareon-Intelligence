import { test } from "node:test";
import assert from "node:assert/strict";
import { enumLabel, sentenceLabel } from "../../src/lib/enum-label.ts";

test("humanizes snake and screaming case", () => {
  assert.equal(enumLabel("url_with_path"), "URL with path");
  assert.equal(enumLabel("URL_WITH_PATH"), "URL with path");
  assert.equal(enumLabel("vendor_research"), "Vendor research");
  assert.equal(enumLabel("VENDOR_RESEARCH"), "Vendor research");
});
test("keeps acronyms", () => {
  assert.equal(enumLabel("ipv4"), "IPv4");
  assert.equal(enumLabel("ipv6_cidr"), "IPv6 CIDR");
  assert.equal(enumLabel("sha256"), "SHA256");
  assert.equal(enumLabel("md5"), "MD5");
  assert.equal(enumLabel("email_domain"), "Email domain");
});
test("unknown, already human, empty", () => {
  assert.equal(enumLabel("weird_new_kind"), "Weird new kind");
  assert.equal(enumLabel("Vendor research"), "Vendor research");
  assert.equal(enumLabel(""), "");
});
test("sentenceLabel capitalises the first letter", () => {
  assert.equal(sentenceLabel("domain"), "Domain");
  assert.equal(sentenceLabel("url_with_path"), "URL with path");
  assert.equal(sentenceLabel("ipv4"), "IPv4");
  assert.equal(sentenceLabel(""), "");
});
test("prototype keys are not treated as acronyms", () => {
  assert.equal(enumLabel("constructor"), "constructor");
  assert.equal(sentenceLabel("constructor"), "Constructor");
  assert.equal(enumLabel("constructor_x"), "Constructor x");
});
