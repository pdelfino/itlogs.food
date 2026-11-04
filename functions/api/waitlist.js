// The landing page's waitlist (#24): a Cloudflare Pages Function that stores an address in D1. Only
// the address, the time and which form it came from are kept. A repeat counts as success, so a
// second click is harmless. A filled hidden field means a bot: it gets a normal answer, nothing
// stored. Anything sent to this list later must carry a working unsubscribe link.

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const SOURCES = new Set(["hero", "end"]);

export function cleanEmail(value) {
  const email = String(value ?? "").trim().toLowerCase();
  return email.length <= 254 && EMAIL.test(email) ? email : null;
}

async function readBody(request) {
  const type = request.headers.get("content-type") || "";
  if (type.includes("application/json")) return request.json();
  return Object.fromEntries(await request.formData());
}

function answer(request, status, body) {
  // a browser with no script posted the form itself: send it back to the page
  if (!(request.headers.get("accept") || "").includes("application/json")) {
    const to = new URL("/", request.url);
    to.searchParams.set("waitlist", body.ok ? "joined" : "error");
    return Response.redirect(to.toString(), 303);
  }
  return Response.json(body, { status });
}

export async function onRequestPost({ request, env }) {
  const origin = request.headers.get("origin");
  if (origin && new URL(origin).host !== new URL(request.url).host) {
    return answer(request, 403, { ok: false, error: "origin" });
  }
  let body;
  try {
    body = await readBody(request);
  } catch {
    return answer(request, 400, { ok: false, error: "body" });
  }
  if (body.website) return answer(request, 200, { ok: true });
  const email = cleanEmail(body.email);
  if (!email) return answer(request, 400, { ok: false, error: "email" });
  const source = SOURCES.has(body.source) ? body.source : "other";
  try {
    await env.DB.prepare(
      "INSERT INTO waitlist (email, source, created_at) VALUES (?1, ?2, ?3) ON CONFLICT(email) DO NOTHING",
    )
      .bind(email, source, new Date().toISOString())
      .run();
  } catch (e) {
    console.error("waitlist insert failed", e);
    return answer(request, 500, { ok: false, error: "store" });
  }
  return answer(request, 200, { ok: true });
}
