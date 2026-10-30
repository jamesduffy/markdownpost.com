import test from "node:test";
import assert from "node:assert/strict";
import { describe, fromLocalInput, toLocalInput } from "../src/schedule.js";

// Run with TZ set (the zone is the browser's, so these tests pin it): TZ=Europe/London node --test tests/
const zone = process.env.TZ;

test("fromLocalInput rejects incomplete values", () => {
  assert.equal(fromLocalInput(""), null);
  assert.equal(fromLocalInput("2026-11-02"), null);
  assert.equal(fromLocalInput(null), null);
});

test("local input round-trips through a UTC instant", () => {
  const iso = fromLocalInput("2026-11-02T14:30");
  assert.match(iso, /^2026-11-02T\d\d:30:00\.000Z$/);
  assert.equal(toLocalInput(new Date(iso)), "2026-11-02T14:30");
});

test("daylight saving: the offset follows the date, not today", { skip: zone !== "Europe/London" }, () => {
  assert.equal(fromLocalInput("2026-07-01T09:00"), "2026-07-01T08:00:00.000Z"); // BST, UTC+1
  assert.equal(fromLocalInput("2026-12-01T09:00"), "2026-12-01T09:00:00.000Z"); // GMT
  assert.equal(fromLocalInput("2026-03-29T02:30"), fromLocalInput("2026-03-29T02:30")); // a time that does not exist still gives an instant
});

test("describe names the zone", () => {
  assert.match(describe("2026-07-01T08:00:00.000Z", "en-GB", "Europe/London"), /BST|GMT\+1/);
  assert.match(describe("2026-12-01T09:00:00.000Z", "en-US", "America/New_York"), /EST|GMT-5/);
});
