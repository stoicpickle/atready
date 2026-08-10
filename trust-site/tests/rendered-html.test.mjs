import assert from "node:assert/strict";
import test from "node:test";

const workerUrl = new URL("../dist/server/index.js", import.meta.url);

async function render(pathname) {
  const versionedWorkerUrl = new URL(workerUrl);
  versionedWorkerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${pathname}`);
  const { default: worker } = await import(versionedWorkerUrl.href);

  return worker.fetch(
    new Request(new URL(pathname, "http://localhost"), {
      headers: { accept: "text/html" },
      redirect: "manual",
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("root directs visitors to the product route", async () => {
  const response = await render("/");
  assert.ok([301, 302, 307, 308].includes(response.status));
  assert.equal(response.headers.get("location"), "/atready");
});

for (const [path, title] of [
  ["/atready", "Product — AtReady"],
  ["/support", "Support — AtReady"],
  ["/privacy", "Privacy — AtReady"],
  ["/terms", "Terms — AtReady"],
  ["/security", "Security — AtReady"],
  ["/surfaces", "Supported surfaces — AtReady"],
]) {
  test(`${path} renders the shared trust shell`, async () => {
    const response = await render(path);
    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

    const html = await response.text();
    assert.match(html, new RegExp(`<title>${title}</title>`, "i"));
    assert.match(html, /Private development/);
    assert.match(html, /not publicly available/i);
    assert.match(html, /href="\/privacy"/);
    assert.match(html, /href="\/security"/);
    assert.match(html, /href="\/support"/);
    assert.doesNotMatch(html, /codex-preview|react-loading-skeleton/i);
  });
}

test("product and policy pages preserve the core trust boundary", async () => {
  const [product, privacy, support, surfaces] = await Promise.all([
    render("/atready").then((response) => response.text()),
    render("/privacy").then((response) => response.text()),
    render("/support").then((response) => response.text()),
    render("/surfaces").then((response) => response.text()),
  ]);

  assert.match(product, /without contacting or running those resources/i);
  assert.match(product, /Local-first is not local-only/i);
  assert.match(product, /Preview/i);
  assert.match(privacy, /sanitized snapshot can enter/i);
  assert.match(privacy, /no hosted backend/i);
  assert.match(support, /Public support is not active/i);
  assert.match(support, /Maintainer finalization/i);
  assert.match(surfaces, /No public support claim yet/i);
  assert.match(surfaces, /The stop \/ go rule/i);
});

test("pre-publication routes allow crawling only to deliver noindex", async () => {
  const product = await render("/atready").then((response) => response.text());
  assert.match(product, /name="robots" content="noindex, nofollow"/i);

  const robots = await render("/robots.txt");
  assert.equal(robots.status, 200);
  const body = await robots.text();
  assert.match(body, /^Allow: \/$/m);
  assert.doesNotMatch(body, /^Disallow:/m);
});
