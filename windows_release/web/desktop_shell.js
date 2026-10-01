const $ = (id) => document.getElementById(id);
const state = { siteUrl: "", poll: null, consentSync: false, hideTimer: null };

async function getState() {
  const response = await fetch("/api/state");
  if (!response.ok) throw new Error("The Windows app could not load its startup information.");
  const data = await response.json();
  state.siteUrl = data.site_url;
  if (data.p3_warning) $("hardware-warning").textContent = data.p3_warning;
  $("website-frame").src = state.siteUrl;
}

async function handleAccountConsent(event) {
  const frame = $("website-frame");
  if (
    !state.siteUrl ||
    event.source !== frame.contentWindow ||
    event.origin !== new URL(state.siteUrl).origin
  ) {
    return;
  }

  const message = event.data;
  if (
    !message ||
    message.type !== "poinsettia-account-consent" ||
    typeof message.eulaVersion !== "string" ||
    typeof message.privacyVersion !== "string" ||
    state.consentSync
  ) {
    return;
  }

  state.consentSync = true;
  $("bootstrap-status").classList.remove("hidden");
  $("bootstrap-message").textContent = "Account consent confirmed. Preparing local models…";
  try {
    const response = await fetch("/api/account-consent", { method: "POST" });
    if (!response.ok) throw new Error("Could not record the account's existing consent.");
    const data = await response.json();
    if (!data.consent_accepted) throw new Error("Could not verify the account's existing consent.");
    await startBootstrap();
  } catch (error) {
    state.consentSync = false;
    $("bootstrap-message").textContent = error.message || "Local model setup could not start.";
  }
}

async function startBootstrap() {
  const response = await fetch("/api/bootstrap/start", { method: "POST" });
  if (!response.ok) throw new Error("Local model setup could not start.");
  await refreshBootstrap();
  if (!state.poll) state.poll = window.setInterval(refreshBootstrap, 1000);
}

async function refreshBootstrap() {
  const response = await fetch("/api/bootstrap/status");
  if (!response.ok) throw new Error("Local model setup status could not be loaded.");
  const data = await response.json();
  const percent = Math.max(0, Math.min(100, Number(data.percent) || 0));
  $("bootstrap-percent").textContent = `${percent}%`;
  $("bootstrap-message").textContent = data.message || "";
  $("bootstrap-progress").style.width = `${percent}%`;
  if (data.phase === "ready" || data.phase === "error") {
    if (state.poll) window.clearInterval(state.poll);
    state.poll = null;
  }
  if (data.phase === "ready" && percent === 100 && !state.hideTimer) {
    state.hideTimer = window.setTimeout(() => {
      $("bootstrap-status").classList.add("hidden");
      state.hideTimer = null;
    }, 3000);
  }
}

window.addEventListener("message", (event) => {
  handleAccountConsent(event).catch((error) => {
    state.consentSync = false;
    $("bootstrap-status").classList.remove("hidden");
    $("bootstrap-message").textContent = error.message || "Local model setup could not start.";
  });
});

getState().catch((error) => {
  $("bootstrap-status").classList.remove("hidden");
  $("bootstrap-message").textContent = error.message;
});