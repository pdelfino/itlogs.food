// make test-site: the waitlist function against a stand-in for D1.
import assert from "node:assert/strict";
import { test } from "node:test";
import { cleanEmail, onRequestPost } from "../functions/api/waitlist.js";

function fakeDB({ fail = false } = {}) {
  const rows = new Map();
  return {
    rows,
    prepare() {
      return {
        bind(email, source, created) {
          return {
            async run() {
              if (fail) throw new Error("db down");
              if (!rows.has(email)) rows.set(email, { source, created });
            },
          };
        },
      };
    },
  };
}

function post(body, { json = true, origin = "https://itlogs.food" } = {}) {
  const headers = { accept: json ? "application/json" : "text/html", origin };
  if (json) {
    headers["content-type"] = "application/json";
    return new Request("https://itlogs.food/api/waitlist", {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
  }
  headers["content-type"] = "application/x-www-form-urlencoded";
  return new Request("https://itlogs.food/api/waitlist", {
    method: "POST",
    headers,
    body: new URLSearchParams(body).toString(),
  });
}

test("an address is stored, trimmed and lowercased, and a repeat changes nothing", async () => {
  const DB = fakeDB();
  const first = await onRequestPost({ request: post({ email: " Ana@Example.COM ", source: "hero" }), env: { DB } });
  assert.deepEqual([first.status, await first.json()], [200, { ok: true }]);
  const again = await onRequestPost({ request: post({ email: "ana@example.com", source: "end" }), env: { DB } });
  assert.equal(again.status, 200);
  assert.deepEqual([...DB.rows.keys()], ["ana@example.com"]);
  assert.equal(DB.rows.get("ana@example.com").source, "hero");
});

test("a filled hidden field looks like success and stores nothing", async () => {
  const DB = fakeDB();
  const r = await onRequestPost({ request: post({ email: "bot@example.com", website: "x" }), env: { DB } });
  assert.deepEqual([r.status, await r.json()], [200, { ok: true }]);
  assert.equal(DB.rows.size, 0);
});

test("a malformed address is refused", async () => {
  for (const email of ["", "nope", "a@b", "a b@c.com", `${"x".repeat(260)}@example.com`]) {
    assert.equal(cleanEmail(email), null);
    const DB = fakeDB();
    const r = await onRequestPost({ request: post({ email }), env: { DB } });
    assert.equal(r.status, 400);
    assert.equal(DB.rows.size, 0);
  }
});

test("another site cannot post to it", async () => {
  const DB = fakeDB();
  const r = await onRequestPost({ request: post({ email: "a@example.com" }, { origin: "https://evil.example" }), env: { DB } });
  assert.equal(r.status, 403);
  assert.equal(DB.rows.size, 0);
});

test("a store failure says so", async () => {
  const r = await onRequestPost({ request: post({ email: "a@example.com" }), env: { DB: fakeDB({ fail: true }) } });
  assert.deepEqual([r.status, (await r.json()).ok], [500, false]);
});

test("a browser with no script is sent back to the page", async () => {
  const DB = fakeDB();
  const r = await onRequestPost({ request: post({ email: "a@example.com", source: "end" }, { json: false }), env: { DB } });
  assert.equal(r.status, 303);
  assert.match(r.headers.get("location"), /waitlist=joined/);
  assert.equal(DB.rows.size, 1);
});
