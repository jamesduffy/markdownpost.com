import test from "node:test";
import assert from "node:assert/strict";
import { MAX_TAGS, addTag, normalizeTag } from "../src/tags.js";

test("normalizeTag lowercases, hyphenates and drops a leading #", () => {
  assert.deepEqual(normalizeTag("#Machine Learning"), { tag: "machine-learning" });
  assert.deepEqual(normalizeTag("  Rust_lang "), { tag: "rust-lang" });
  assert.deepEqual(normalizeTag("ＡＩ"), { tag: "ai" }); // NFKC folds full-width letters
});

test("normalizeTag refuses what the server refuses", () => {
  for (const bad of ["a", "x".repeat(31), "café", "a--b", "-a", "a!", "admin", "日本語"]) assert.ok(normalizeTag(bad).error, bad);
});

test("addTag ignores repeats and stops at the limit", () => {
  let list = [];
  for (const t of ["one", "two", "three", "four", "five"]) list = addTag(list, t).list;
  assert.equal(list.length, MAX_TAGS);
  assert.equal(addTag(list, "ONE").list, list); // repeat: unchanged, no error
  assert.equal(addTag(list, "ONE").error, undefined);
  assert.ok(addTag(list, "six").error);
});
