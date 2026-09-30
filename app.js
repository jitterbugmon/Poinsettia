(() => {
  "use strict";

  const configuredRepository = globalThis.POINSETTIA_SITE_CONFIG?.repository;
  const repository = typeof configuredRepository === "string" &&
    /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(configuredRepository)
    ? configuredRepository : "jitterbugmon/Poinsettia";
  const latestApiUrl = `https://api.github.com/repos/${repository}/releases/latest`;
  const setupName = /^Poinsettia-[A-Za-z0-9][A-Za-z0-9._-]*-Windows-x64-Setup\.exe$/;
  const installLinks = Array.from(document.querySelectorAll("[data-install]"));
  const status = document.getElementById("release-status");
  const indicator = document.querySelector(".release-indicator");

  document.querySelectorAll("[data-release-link]").forEach((link) => {
    link.href = `https://github.com/${repository}/releases`;
  });
  document.querySelectorAll("[data-source-link]").forEach((link) => {
    link.href = `https://github.com/${repository}`;
  });

  function setStatus(message, available) {
    status.textContent = message;
    indicator.classList.toggle("available", available);
  }

  function findInstaller(release) {
    if (!release || !Array.isArray(release.assets)) return null;
    return release.assets.find((asset) => {
      if (!setupName.test(asset.name) || !Number.isFinite(asset.size) || asset.size < 1) {
        return false;
      }
      try {
        const url = new URL(asset.browser_download_url);
        return url.protocol === "https:" && url.hostname === "github.com" &&
          url.pathname.startsWith(`/${repository}/releases/download/`);
      } catch (_) {
        return false;
      }
    }) || null;
  }

  installLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      if (link.getAttribute("aria-disabled") === "true") {
        event.preventDefault();
        status.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    });
  });

  async function checkRelease() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(latestApiUrl, {
        headers: { "Accept": "application/vnd.github+json" },
        cache: "no-store",
        signal: controller.signal
      });
      if (!response.ok) throw new Error(`GitHub returned HTTP ${response.status}`);
      const release = await response.json();
      const installer = findInstaller(release);
      if (!installer) {
        setStatus("No Windows installer is published yet. Check the official releases page for updates.", false);
        return;
      }
      installLinks.forEach((link) => {
        link.href = installer.browser_download_url;
        link.removeAttribute("aria-disabled");
        link.removeAttribute("tabindex");
        link.setAttribute("aria-label", `Download ${installer.name} from GitHub`);
      });
      const version = typeof release.tag_name === "string" && /^v\d/.test(release.tag_name)
        ? ` ${release.tag_name}` : "";
      setStatus(`Poinsettia${version} for Windows is ready to download. Open the installer after it finishes.`, true);
    } catch (_) {
      setStatus("Couldn't check the latest installer. Use the official releases page instead.", false);
    } finally {
      clearTimeout(timeout);
    }
  }

  checkRelease();
})();