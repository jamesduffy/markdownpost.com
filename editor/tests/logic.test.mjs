import test from "node:test";
import assert from "node:assert/strict";
import { canMarkSynced, classifyFailure, clientIdFor, lonelySlash, menuDrafts, primaryLabel, publishedMessage, restorableNew, savedStatus } from "../src/logic.js";

test("classifyFailure", () => {
  assert.equal(classifyFailure(0), "transient");
  assert.equal(classifyFailure(500), "transient");
  assert.equal(classifyFailure(401), "auth");
  assert.equal(classifyFailure(403), "auth");
  assert.equal(classifyFailure(404), "gone");
  assert.equal(classifyFailure(409), "conflict");
  assert.equal(classifyFailure(400), "rejected");
  assert.equal(classifyFailure(413), "rejected");
});

test("clientIdFor is stable for a draft key and valid for the server", () => {
  const uuid = "3f2b8c1e-5a4d-4e0b-9a77-0c1d2e3f4a5b";
  assert.equal(clientIdFor(`new-${uuid}`), uuid);
  assert.equal(clientIdFor(`new-${uuid}`), clientIdFor(`new-${uuid}`));
  assert.match(clientIdFor("12", () => "generated-id-1234"), /^generated-id-1234$/);
});

test("failed drafts are not restored by default but stay in the menu", () => {
  const ok = { key: "new-a", title: "a", body: "", synced: false, savedAt: 1 };
  const bad = { key: "new-b", title: "b", body: "x", synced: false, failed: true, savedAt: 2 };
  const posted = { key: "5", postId: "5", title: "p", synced: false, savedAt: 3 };
  assert.deepEqual(restorableNew([ok, bad, posted]).map((d) => d.key), ["new-a"]);
  assert.deepEqual(menuDrafts([ok, bad, posted], "none").map((d) => d.key), ["new-b", "new-a"]);
  assert.deepEqual(menuDrafts([ok, bad], "new-a").map((d) => d.key), ["new-b"]);
});

test("canMarkSynced never marks a rejected or pending save as synced", () => {
  assert.equal(canMarkSynced({ postId: "1", dirty: false, failed: false }), true);
  assert.equal(canMarkSynced({ postId: "1", dirty: false, failed: true }), false);
  assert.equal(canMarkSynced({ postId: "1", dirty: true, failed: false }), false);
  assert.equal(canMarkSynced({ postId: null, dirty: false, failed: false }), false);
});

test("primary button names what it will do", () => {
  assert.equal(primaryLabel({ isDraft: true, visibility: "public" }), "Publish");
  assert.equal(primaryLabel({ isDraft: true, visibility: "unlisted" }), "Publish (unlisted)");
  assert.equal(primaryLabel({ isDraft: true, visibility: "private" }), "Save privately");
  for (const v of ["public", "unlisted", "private"]) assert.equal(primaryLabel({ isDraft: false, visibility: v }), "Update");
});

test("status and success wording", () => {
  assert.equal(savedStatus({ isDraft: true, visibility: "public" }), "Draft, autosaved");
  assert.equal(savedStatus({ isDraft: false, visibility: "public" }), "Published, changes saved");
  assert.equal(savedStatus({ isDraft: false, visibility: "private" }), "Saved privately");
  assert.match(publishedMessage("public"), /^Published\./);
  assert.match(publishedMessage("unlisted"), /unlisted/);
  assert.match(publishedMessage("private"), /Only you/);
});

test("lonelySlash removes only a lone slash that opened the menu", () => {
  assert.deepEqual(lonelySlash("/", 1, 10), { from: 10, to: 11 });
  assert.deepEqual(lonelySlash("  /", 3, 10), { from: 12, to: 13 });
  assert.equal(lonelySlash("/h", 2, 0), null); // something was typed after it
  assert.equal(lonelySlash("a /", 3, 0), null); // not at the start of the line
  assert.equal(lonelySlash("//", 2, 0), null);
});
