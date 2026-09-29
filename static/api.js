/* Shared JSON fetch helper for public + admin pages. */
function getCookie(name) {
  const candidates = [name, `__Host-${name}`];
  for (const part of document.cookie.split("; ")) {
    const [key, ...rest] = part.split("=");
    if (candidates.includes(key)) return decodeURIComponent(rest.join("="));
  }
  return "";
}

async function apiRequest(url, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const csrf = getCookie("csrf_token");
  if (csrf) headers["X-CSRF-Token"] = csrf;
  let response;
  try {
    response = await fetch(url, { ...options, headers, credentials: "same-origin" });
  } catch (error) {
    const hint = window.location.protocol === "file:"
      ? "Abre la app en http://127.0.0.1:8000 (no como archivo local)."
      : "No hay conexión con el servidor. Reinicia uvicorn y recarga la página.";
    throw new Error(hint);
  }
  const raw = await response.text();
  let body = {};
  try {
    body = raw ? JSON.parse(raw) : {};
  } catch {
    throw new Error(response.ok ? "Respuesta inválida del servidor." : "Error interno del servidor.");
  }
  if (!response.ok) {
    throw new Error(typeof body.detail === "string" ? body.detail : "No fue posible completar la operación.");
  }
  return body;
}
