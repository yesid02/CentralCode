const form = document.querySelector("#lookup-form");
const platform = document.querySelector("#platform");
const codeType = document.querySelector("#code-type");
const identifier = document.querySelector("#identifier");
const submitButton = document.querySelector("#submit-button");
const result = document.querySelector("#result");
const resultLabel = document.querySelector("#result-label");
const codeElement = document.querySelector("#code");
const expiresElement = document.querySelector("#expires");
const subscriptionElement = document.querySelector("#subscription");
const accessBadge = document.querySelector("#access-badge");
const renewalBox = document.querySelector("#renewal");
const renewalMessage = document.querySelector("#renewal-message");
const whatsappButton = document.querySelector("#whatsapp-button");
const message = document.querySelector("#message");
const copyButton = document.querySelector("#copy-button");
const linkButton = document.querySelector("#link-button");
let countdown;
let subscriptionCountdown;

function clearCountdowns() {
  clearInterval(countdown);
  clearInterval(subscriptionCountdown);
}

function hideLinkFallback() {
  linkButton.hidden = true;
  linkButton.removeAttribute("href");
  copyButton.hidden = false;
  codeElement.hidden = false;
  resultLabel.textContent = "Tu código es";
}

function showCountdown(seconds) {
  clearInterval(countdown);
  let remaining = seconds;
  const tick = () => {
    expiresElement.textContent = remaining > 0
      ? `El código vence en ${remaining} segundos`
      : "El código ha vencido.";
    if (remaining <= 0) clearInterval(countdown);
    remaining -= 1;
  };
  tick();
  countdown = setInterval(tick, 1000);
}

function showAccessBadge(daysRemaining, urgency, secondsRemaining) {
  const color = urgency || "red";
  accessBadge.hidden = false;
  accessBadge.className = `badge ${color}`;
  const seconds = secondsRemaining ?? ((daysRemaining ?? 0) * 86400);
  if (seconds <= 0) {
    accessBadge.textContent = "Acceso vencido";
    return;
  }
  const days = Math.max(0, Math.floor(seconds / 86400));
  if (days >= 1) {
    accessBadge.textContent = days === 1 ? "1 día restante" : `${days} días restantes`;
    return;
  }
  const hours = Math.max(1, Math.ceil(seconds / 3600));
  accessBadge.textContent = hours === 1 ? "1 hora restante" : `${hours} h restantes`;
}

function showSubscriptionCountdown(secondsRemaining, expiresAt, urgency) {
  clearInterval(subscriptionCountdown);
  let remaining = secondsRemaining;
  const endLabel = expiresAt
    ? new Date(expiresAt).toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" })
    : "";

  const tick = () => {
    showAccessBadge(null, urgency, remaining);
    if (remaining <= 0) {
      subscriptionElement.textContent = endLabel
        ? `Tu acceso venció el ${endLabel}.`
        : "Tu acceso a esta cuenta ya venció.";
      clearInterval(subscriptionCountdown);
      return;
    }
    const days = Math.floor(remaining / 86400);
    const hours = Math.floor((remaining % 86400) / 3600);
    const minutes = Math.floor((remaining % 3600) / 60);
    const seconds = remaining % 60;
    const parts = [];
    if (days > 0) parts.push(`${days}d`);
    if (hours > 0 || days > 0) parts.push(`${hours}h`);
    parts.push(`${minutes}m`, `${seconds}s`);
    subscriptionElement.textContent = `Acceso válido hasta ${endLabel}. Quedan ${parts.join(" ")}.`;
    remaining -= 1;
  };
  tick();
  subscriptionCountdown = setInterval(tick, 1000);
}

function showRenewal(payload) {
  hideLinkFallback();
  renewalBox.hidden = false;
  renewalMessage.textContent = payload.message || "Tu acceso venció. Renueva por WhatsApp con el bot.";
  whatsappButton.href = payload.renewal?.url || "#";
  showAccessBadge(0, "red");
  result.hidden = false;
  codeElement.textContent = "—";
  expiresElement.textContent = "";
  subscriptionElement.textContent = "";
}

function showLinkFallback(payload) {
  result.hidden = false;
  resultLabel.textContent = "Abre el enlace para ver tu código";
  codeElement.textContent = "";
  codeElement.hidden = true;
  copyButton.hidden = true;
  linkButton.hidden = false;
  linkButton.href = payload.link_url;
  expiresElement.textContent = "El enlace de Netflix suele vencer en unos minutos.";
  message.textContent = payload.message
    || "No pudimos leer el código automáticamente. Ábrelo en Netflix.";
  if (payload.seconds_remaining != null) {
    showSubscriptionCountdown(payload.seconds_remaining, payload.account_expires_at, payload.urgency);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.textContent = "";
  result.hidden = true;
  accessBadge.hidden = true;
  renewalBox.hidden = true;
  hideLinkFallback();
  clearCountdowns();

  const phone = identifier.value.trim();
  if (phone.replace(/\D/g, "").length < 7) {
    message.textContent = "Ingresa un número de celular válido.";
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = "Buscando...";
  try {
    const payload = await apiRequest("/api/lookup", {
      method: "POST",
      body: JSON.stringify({
        platform: platform.value,
        identifier: phone,
        code_type: codeType.value || "login",
      }),
    });
    if (payload.expired) {
      showRenewal(payload);
      return;
    }
    if (payload.code) {
      codeElement.hidden = false;
      codeElement.textContent = payload.code;
      copyButton.hidden = false;
      linkButton.hidden = true;
      resultLabel.textContent = "Tu código es";
      result.hidden = false;
      showCountdown(payload.expires_in);
      showSubscriptionCountdown(payload.seconds_remaining, payload.account_expires_at, payload.urgency);
      return;
    }
    if (payload.link_url) {
      showLinkFallback(payload);
      return;
    }
    message.textContent = payload.message
      || "No se encontró código para tu correo asociado o tu cuenta ya venció.";
    if (payload.seconds_remaining != null) {
      showSubscriptionCountdown(payload.seconds_remaining, payload.account_expires_at, payload.urgency);
      result.hidden = false;
      codeElement.textContent = "—";
      expiresElement.textContent = "";
    }
  } catch (error) {
    message.textContent = error.message;
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Consultar código";
  }
});

copyButton.addEventListener("click", async () => {
  await navigator.clipboard.writeText(codeElement.textContent);
  copyButton.textContent = "¡Copiado!";
  setTimeout(() => { copyButton.textContent = "Copiar código"; }, 1500);
});

async function loadPlatformOptions(retries = 3) {
  let lastError;
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    try {
      const platforms = await apiRequest("/api/platforms");
      while (platform.options.length > 1) platform.remove(1);
      platforms.forEach(({ key, label }) => platform.add(new Option(label, key)));
      if (!platforms.length) {
        message.textContent = "No hay plataformas. Agrega productos activos en Tienda (admin).";
      } else {
        message.textContent = "";
      }
      return;
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 400 * attempt));
    }
  }
  message.textContent = lastError?.message || "No se pudieron cargar las plataformas.";
}

loadPlatformOptions();
