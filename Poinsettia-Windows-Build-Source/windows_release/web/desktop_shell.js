const $ = (id) => document.getElementById(id);
const state = { reviewed: false, siteUrl: "", poll: null };

async function getState() {
  const response = await fetch("/api/state");
  const data = await response.json();
  state.siteUrl = data.site_url;
  if (data.p3_warning) $("hardware-warning").textContent = data.p3_warning;
  if (data.consent_accepted) showWebsite();
}

async function openLegal(documentName) {
  try {
    const response = await fetch(`/api/legal/${documentName}`);
    if (!response.ok) throw new Error("The legal document could not be loaded.");
    $("legal-title").textContent = documentName === "privacy" ? "Privacy Policy" : "User Agreement";
    $("legal-content").textContent = await response.text();
    $("legal-dialog").showModal();
    if (documentName === "eula") {
      state.reviewed = true;
      $("accept-eula").disabled = false;
    }
  } catch (error) {
    $("gate-error").textContent = error.message;
  }
}

function showWebsite() {
  $("legal-gate").classList.add("hidden");
  $("website-frame").src = state.siteUrl;
  $("website-frame").classList.add("visible");
  $("bootstrap-status").classList.remove("hidden");
  startBootstrap();
}

async function acceptEula() {
  $("gate-error").textContent = "";
  const response = await fetch("/api/consent", { method: "POST" });
  if (!response.ok) {
    $("gate-error").textContent = "Could not save your acceptance. Please try again.";
    return;
  }
  showWebsite();
}

async function startBootstrap() {
  await fetch("/api/bootstrap/start", { method: "POST" });
  await refreshBootstrap();
  state.poll = window.setInterval(refreshBootstrap, 1000);
}

async function refreshBootstrap() {
  const response = await fetch("/api/bootstrap/status");
  const data = await response.json();
  const percent = Math.max(0, Math.min(100, Number(data.percent) || 0));
  $("bootstrap-percent").textContent = `${percent}%`;
  $("bootstrap-message").textContent = data.message || "";
  $("bootstrap-progress").style.width = `${percent}%`;
  if (data.phase === "ready" || data.phase === "error") {
    if (state.poll) window.clearInterval(state.poll);
    state.poll = null;
  }
}

$("open-eula").addEventListener("click", () => openLegal("eula"));
$("accept-eula").addEventListener("change", (event) => {
  $("accept-button").disabled = !state.reviewed || !event.target.checked;
});
$("accept-button").addEventListener("click", acceptEula);
$("open-privacy").addEventListener("click", () => openLegal("privacy"));
$("close-legal").addEventListener("click", () => $("legal-dialog").close());
$("legal-dialog-close").addEventListener("click", () => $("legal-dialog").close());
getState().catch((error) => { $("gate-error").textContent = error.message; });