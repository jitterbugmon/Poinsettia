const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../docs/app.js"), "utf8");

async function runPage(response) {
  const links = Array.from({ length: 2 }, () => {
    const attributes = new Map([["aria-disabled", "true"]]);
    return {
      attributes,
      href: "",
      addEventListener() {},
      getAttribute(name) { return attributes.get(name); },
      setAttribute(name, value) { attributes.set(name, value); },
      removeAttribute(name) { attributes.delete(name); },
    };
  });
  const status = { textContent: "" };
  const indicator = {
    available: false,
    classList: { toggle(_name, state) { indicator.available = state; } },
  };
  const document = {
    querySelectorAll() { return links; },
    querySelector() { return indicator; },
    getElementById() { return status; },
  };
  let requestedUrl = "";
  const fetch = async (url) => {
    requestedUrl = url;
    return response;
  };
  vm.runInNewContext(script, { document, fetch, URL });
  await new Promise((resolve) => setImmediate(resolve));
  return { links, status, indicator, requestedUrl };
}

test("activates both download buttons only for the latest official installer", async () => {
  const download = "https://github.com/jitterbugmon/Poinsettia/releases/download/v4.0.1/Poinsettia-4.0.1-Windows-x64-Setup.exe";
  const result = await runPage({
    ok: true,
    json: async () => ({
      tag_name: "v4.0.1",
      assets: [
        { name: "Poinsettia-4.0.1-Windows-x64-Setup.exe", size: 1234, browser_download_url: download },
      ],
    }),
  });
  assert.equal(result.requestedUrl, "https://api.github.com/repos/jitterbugmon/Poinsettia/releases/latest");
  assert.equal(result.indicator.available, true);
  assert.match(result.status.textContent, /v4\.0\.1.*ready to download/);
  for (const link of result.links) {
    assert.equal(link.href, download);
    assert.equal(link.getAttribute("aria-disabled"), undefined);
  }
});

test("does not offer a download when the latest release has no installer", async () => {
  const result = await runPage({ ok: true, json: async () => ({ assets: [] }) });
  assert.match(result.status.textContent, /No Windows installer is published yet/);
  assert.equal(result.indicator.available, false);
  for (const link of result.links) {
    assert.equal(link.href, "");
    assert.equal(link.getAttribute("aria-disabled"), "true");
  }
});

test("rejects an installer whose download URL is not the official release", async () => {
  const result = await runPage({
    ok: true,
    json: async () => ({
      assets: [
        {
          name: "Poinsettia-4.0.1-Windows-x64-Setup.exe",
          size: 1234,
          browser_download_url: "https://example.com/Poinsettia-4.0.1-Windows-x64-Setup.exe",
        },
      ],
    }),
  });
  assert.equal(result.links[0].getAttribute("aria-disabled"), "true");
});

test("shows a release-page fallback when GitHub cannot be checked", async () => {
  const result = await runPage({ ok: false, status: 503 });
  assert.match(result.status.textContent, /Couldn't check the latest installer/);
  assert.equal(result.links[0].getAttribute("aria-disabled"), "true");
});