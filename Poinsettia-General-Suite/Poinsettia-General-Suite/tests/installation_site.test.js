const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const siteRoot = path.join(__dirname, "../poinsettia-installation-site");
const script = fs.readFileSync(path.join(siteRoot, "app.js"), "utf8");

async function runPage(response, repository = "jitterbugmon/Poinsettia") {
  const installLinks = Array.from({ length: 2 }, () => {
    const attributes = new Map([["aria-disabled", "true"], ["tabindex", "-1"]]);
    return {
      href: "",
      addEventListener() {},
      getAttribute(name) { return attributes.get(name); },
      setAttribute(name, value) { attributes.set(name, value); },
      removeAttribute(name) { attributes.delete(name); }
    };
  });
  const releaseLinks = [{ href: "" }];
  const sourceLinks = [{ href: "" }];
  const status = { textContent: "" };
  const indicator = { classList: { toggle() {} } };
  const document = {
    querySelectorAll(selector) {
      return {
        "[data-install]": installLinks,
        "[data-release-link]": releaseLinks,
        "[data-source-link]": sourceLinks
      }[selector] || [];
    },
    querySelector() { return indicator; },
    getElementById() { return status; }
  };
  let requestedUrl = "";
  vm.runInNewContext(script, {
    document, URL, AbortController, setTimeout, clearTimeout,
    POINSETTIA_SITE_CONFIG: { repository },
    fetch: async (url) => {
      requestedUrl = url;
      return response;
    }
  });
  await new Promise((resolve) => setImmediate(resolve));
  return { installLinks, releaseLinks, sourceLinks, status, requestedUrl };
}

function releaseResponse(url, size = 1000) {
  return {
    ok: true,
    json: async () => ({
      tag_name: "v4.0.1",
      assets: [{
        name: "Poinsettia-4.0.1-Windows-x64-Setup.exe",
        size,
        browser_download_url: url
      }]
    })
  };
}

test("the folder includes all its local frontend dependencies", () => {
  const html = fs.readFileSync(path.join(siteRoot, "index.html"), "utf8");
  const refs = [...html.matchAll(/(?:src|href)="\.\/([^"]+)"/g)].map((match) => match[1]);
  for (const ref of refs) assert.ok(fs.existsSync(path.join(siteRoot, ref)), ref);
  for (const name of ["config.js", ".nojekyll", "assets/poinsettia-logo.png"]) {
    assert.ok(fs.existsSync(path.join(siteRoot, name)));
  }
  assert.equal(fs.existsSync(path.join(siteRoot, "main.py")), false);
  assert.equal(fs.existsSync(path.join(siteRoot, "poinsettia.db")), false);
});

test("activates both installer links for an official release asset", async () => {
  const download = "https://github.com/jitterbugmon/Poinsettia/releases/download/v4.0.1/Poinsettia-4.0.1-Windows-x64-Setup.exe";
  const result = await runPage(releaseResponse(download));
  for (const link of result.installLinks) {
    assert.equal(link.href, download);
    assert.equal(link.getAttribute("aria-disabled"), undefined);
    assert.equal(link.getAttribute("tabindex"), undefined);
  }
  assert.match(result.status.textContent, /v4\.0\.1.*ready to download/);
});

test("missing installers leave downloads disabled with a clear notice", async () => {
  const result = await runPage({ ok: true, json: async () => ({ assets: [] }) });
  assert.match(result.status.textContent, /No Windows installer is published yet/);
  assert.equal(result.installLinks[0].getAttribute("aria-disabled"), "true");
  assert.equal(result.releaseLinks[0].href, "https://github.com/jitterbugmon/Poinsettia/releases");
});

test("does not trust third-party, wrong-repository, or empty downloads", async () => {
  for (const [url, size] of [
    ["https://example.com/setup.exe", 1000],
    ["https://github.com/other/repo/releases/download/v4/setup.exe", 1000],
    ["https://github.com/jitterbugmon/Poinsettia/releases/download/v4/setup.exe", 0]
  ]) {
    const result = await runPage(releaseResponse(url, size));
    assert.equal(result.installLinks[0].getAttribute("aria-disabled"), "true");
  }
});

test("GitHub API failures do not produce broken download links", async () => {
  const result = await runPage({ ok: false, status: 403 });
  assert.match(result.status.textContent, /Couldn't check the latest installer/);
  assert.equal(result.installLinks[0].href, "");
});

test("a configurable release repository need not match the website repository", async () => {
  const repository = "example/Poinsettia";
  const download = `https://github.com/${repository}/releases/download/v4.0.1/Poinsettia-4.0.1-Windows-x64-Setup.exe`;
  const result = await runPage(releaseResponse(download), repository);
  assert.equal(result.requestedUrl, `https://api.github.com/repos/${repository}/releases/latest`);
  assert.equal(result.installLinks[0].href, download);
  assert.equal(result.sourceLinks[0].href, `https://github.com/${repository}`);
});