const state = {
  language: localStorage.getItem("poinsettia_windows_language") || "en",
  reviewed: false,
  accepted: false,
  poll: null,
};

const copy = {
  en: {
    legalKicker: "Required before use",
    gateTitle: "Review the Poinsettia User Agreement",
    gateCopy: "The Windows release is blocked until you review and accept the current local-use terms.",
    readEula: "Read the User Agreement",
    acceptEula: "I have reviewed and accept the current User Agreement.",
    continue: "Accept and continue",
    language: "Language",
    firstBoot: "FIRST BOOT",
    localModels: "Prepare local AI models",
    readyToCheck: "Ready to check the local AI runtime.",
    startSetup: "Start local model setup",
    privateLocal: "PRIVATE LOCAL CHAT",
    chatTitle: "Ask Poinsettia",
    promptPlaceholder: "Ask a question…",
    send: "Send",
    privacy: "Privacy Policy",
    close: "Close",
    you: "You",
    assistant: "Poinsettia",
    setupStarted: "Preparing the local runtime…",
    acceptError: "Could not save your acceptance. Please try again.",
    runtimeError: "The local runtime returned an error.",
  },
  es: {
    legalKicker: "Requerido antes de usar",
    gateTitle: "Revisa el Acuerdo de usuario de Poinsettia",
    gateCopy: "La versión de Windows está bloqueada hasta que revises y aceptes los términos actuales.",
    readEula: "Leer el Acuerdo de usuario",
    acceptEula: "He revisado y acepto el Acuerdo de usuario actual.",
    continue: "Aceptar y continuar",
    language: "Idioma",
    firstBoot: "PRIMER INICIO",
    localModels: "Preparar modelos de IA locales",
    readyToCheck: "Listo para comprobar el motor local de IA.",
    startSetup: "Iniciar configuración local",
    privateLocal: "CHAT LOCAL PRIVADO",
    chatTitle: "Pregúntale a Poinsettia",
    promptPlaceholder: "Escribe una pregunta…",
    send: "Enviar",
    privacy: "Política de privacidad",
    close: "Cerrar",
    you: "Tú",
    assistant: "Poinsettia",
    setupStarted: "Preparando el motor local…",
    acceptError: "No se pudo guardar la aceptación. Inténtalo de nuevo.",
    runtimeError: "El motor local devolvió un error.",
  },
};

const $ = (id) => document.getElementById(id);
const text = (key) => copy[state.language][key] || copy.en[key] || key;

function applyLanguage() {
  document.documentElement.lang = state.language === "es" ? "es" : "en";
  document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = text(node.dataset.i18n); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => { node.placeholder = text(node.dataset.i18nPlaceholder); });
  $("language").value = state.language;
}

function addMessage(role, content) {
  const node = document.createElement("p");
  node.className = "message";
  const label = document.createElement("strong");
  label.textContent = role === "user" ? text("you") : text("assistant");
  node.append(label, document.createTextNode(content));
  $("messages").append(node);
  $("messages").scrollTop = $("messages").scrollHeight;
  return node;
}

async function refreshState() {
  const response = await fetch("/api/state");
  const data = await response.json();
  state.accepted = Boolean(data.consent_accepted);
  $("legal-gate").classList.toggle("hidden", state.accepted);
  $("app-shell").classList.toggle("hidden", !state.accepted);
  if (data.p3_warning) {
    $("hardware-warning").textContent = data.p3_warning;
    $("hardware-warning").classList.remove("hidden");
  }
  if (state.accepted) {
    await refreshBootstrap();
  }
}

async function openLegal(documentName) {
  try {
    const response = await fetch(`/api/legal/${documentName}`);
    if (!response.ok) throw new Error("The legal document could not be loaded.");
    $("legal-title").textContent = documentName === "privacy" ? text("privacy") : text("gateTitle");
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

async function acceptEula() {
  $("gate-error").textContent = "";
  const response = await fetch("/api/consent", { method: "POST" });
  if (!response.ok) {
    $("gate-error").textContent = text("acceptError");
    return;
  }
  state.accepted = true;
  $("legal-gate").classList.add("hidden");
  $("app-shell").classList.remove("hidden");
  await refreshBootstrap();
}

async function startBootstrap() {
  $("setup-start").disabled = true;
  $("setup-message").textContent = text("setupStarted");
  await fetch("/api/bootstrap/start", { method: "POST" });
  await refreshBootstrap();
  state.poll = window.setInterval(refreshBootstrap, 1000);
}

async function refreshBootstrap() {
  const response = await fetch("/api/bootstrap/status");
  const data = await response.json();
  const percent = Math.max(0, Math.min(100, Number(data.percent) || 0));
  $("setup-percent").textContent = `${percent}%`;
  $("setup-progress").style.width = `${percent}%`;
  $("setup-message").textContent = data.message || "";
  if (data.phase === "ready" || data.phase === "error") {
    $("setup-start").disabled = data.phase === "ready";
    if (state.poll) { window.clearInterval(state.poll); state.poll = null; }
  }
}

async function sendMessage(event) {
  event.preventDefault();
  const prompt = $("prompt").value.trim();
  if (!prompt) return;
  $("prompt").value = "";
  addMessage("user", prompt);
  const assistant = addMessage("assistant", "");
  const assistantText = document.createTextNode("");
  assistant.append(assistantText);
  const history = [{ role: "user", content: prompt }];
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: $("mode").value, messages: history }),
    });
    if (!response.ok) throw new Error(text("runtimeError"));
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      buffer += decoder.decode(result.value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      lines.filter(Boolean).forEach((line) => {
        const item = JSON.parse(line);
        if (item.error) throw new Error(item.error);
        assistantText.textContent += item.message?.content || "";
      });
      $("messages").scrollTop = $("messages").scrollHeight;
    }
  } catch (error) {
    $("chat-error").textContent = error.message || text("runtimeError");
  }
}

$("language").addEventListener("change", (event) => {
  state.language = event.target.value;
  localStorage.setItem("poinsettia_windows_language", state.language);
  applyLanguage();
});
$("open-eula").addEventListener("click", () => openLegal("eula"));
$("open-privacy").addEventListener("click", () => openLegal("privacy"));
$("close-legal").addEventListener("click", () => $("legal-dialog").close());
$("legal-dialog-close").addEventListener("click", () => $("legal-dialog").close());
$("accept-eula").addEventListener("change", (event) => {
  $("accept-button").disabled = !state.reviewed || !event.target.checked;
});
$("accept-button").addEventListener("click", acceptEula);
$("setup-start").addEventListener("click", startBootstrap);
$("chat-form").addEventListener("submit", sendMessage);
applyLanguage();
refreshState().catch((error) => { $("gate-error").textContent = error.message; });