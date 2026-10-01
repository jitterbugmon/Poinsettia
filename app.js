(() => {
  "use strict";

  const configuredRepository = globalThis.POINSETTIA_SITE_CONFIG?.repository;
  const repository = typeof configuredRepository === "string" &&
    /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(configuredRepository)
    ? configuredRepository : "jitterbugmon/Poinsettia";
  const baseUrl = `https://github.com/${repository}`;

  document.querySelectorAll("[data-release-link]").forEach((link) => {
    link.href = `${baseUrl}/releases`;
  });
  document.querySelectorAll("[data-source-link]").forEach((link) => {
    link.href = baseUrl;
  });
})();