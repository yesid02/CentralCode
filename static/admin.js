const loginView = document.querySelector("#login-view");
const dashboard = document.querySelector("#dashboard");
const loginMessage = document.querySelector("#login-message");
const dashboardMessage = document.querySelector("#dashboard-message");
const panelTitle = document.querySelector("#panel-title");
const panelEyebrow = document.querySelector("#panel-eyebrow");
const accountPlatform = document.querySelector("#account-platform");
const accountMain = document.querySelector("#account-main");
const accountEmail = document.querySelector("#account-email");
const accountPassword = document.querySelector("#account-password");
const aliasPreview = document.querySelector("#alias-preview");
const assignmentClient = document.querySelector("#assignment-client");
const assignmentAccount = document.querySelector("#assignment-account");

let data = {
  summary: null,
  main_accounts: [],
  accounts: [],
  clients: [],
  assignments: [],
  shop: { products: [], combos: [], discounts: [], stock: [], summary: {} },
  platforms: [],
  audit: [],
};
let messageTimer;
let shopTab = "products";

const PANEL_META = {
  overview: { title: "Resumen", eyebrow: "ESTADO GENERAL" },
  main: { title: "Cuentas principales", eyebrow: "BANDEJAS IMAP" },
  streaming: { title: "Cuentas streaming", eyebrow: "PLATAFORMAS" },
  clients: { title: "Clientes", eyebrow: "ACCESOS" },
  assign: { title: "Asociar cuentas", eyebrow: "VÍNCULOS" },
  shop: { title: "Tienda", eyebrow: "CATÁLOGO Y STOCK" },
};

const AUDIT_LABELS = {
  login_success: { label: "Inicio de sesión", tone: "ok" },
  login_failed: { label: "Intento fallido", tone: "bad" },
  logout: { label: "Cierre de sesión", tone: "muted" },
  main_account_create: { label: "Cuenta principal creada", tone: "ok" },
  main_account_update: { label: "Cuenta principal editada", tone: "info" },
  main_account_delete: { label: "Cuenta principal eliminada", tone: "bad" },
  main_account_password_update: { label: "Contraseña IMAP actualizada", tone: "info" },
  account_create: { label: "Cuenta streaming creada", tone: "ok" },
  account_update: { label: "Cuenta streaming editada", tone: "info" },
  account_delete: { label: "Cuenta streaming eliminada", tone: "bad" },
  account_renew: { label: "Cuenta renovada", tone: "ok" },
  client_create: { label: "Cliente creado", tone: "ok" },
  client_update: { label: "Cliente editado", tone: "info" },
  client_delete: { label: "Cliente eliminado", tone: "bad" },
  assignment_create: { label: "Cuenta asociada", tone: "ok" },
  assignment_delete: { label: "Asociación quitada", tone: "bad" },
  shop_product_create: { label: "Producto creado", tone: "ok" },
  shop_product_update: { label: "Producto editado", tone: "info" },
  shop_product_delete: { label: "Producto eliminado", tone: "bad" },
  shop_combo_create: { label: "Combo creado", tone: "ok" },
  shop_combo_update: { label: "Combo editado", tone: "info" },
  shop_combo_delete: { label: "Combo eliminado", tone: "bad" },
  shop_discount_create: { label: "Descuento creado", tone: "ok" },
  shop_discount_update: { label: "Descuento editado", tone: "info" },
  shop_discount_delete: { label: "Descuento eliminado", tone: "bad" },
  shop_stock_create: { label: "Stock agregado", tone: "ok" },
  shop_stock_update: { label: "Stock editado", tone: "info" },
  shop_stock_delete: { label: "Stock eliminado", tone: "bad" },
};

const request = apiRequest;

function showPanel(panelKey) {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.panel === panelKey);
  });
  document.querySelectorAll(".admin-panel").forEach((panel) => {
    const active = panel.dataset.panel === panelKey;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  });
  const meta = PANEL_META[panelKey] || PANEL_META.overview;
  panelTitle.textContent = meta.title;
  panelEyebrow.textContent = meta.eyebrow;
}

function setMessage(text, ok = false) {
  clearTimeout(messageTimer);
  dashboardMessage.textContent = text;
  dashboardMessage.className = ok ? "message ok top-message" : "message top-message";
  messageTimer = setTimeout(() => { dashboardMessage.textContent = ""; }, 4000);
}

async function runAction(fn) {
  try {
    await fn();
  } catch (error) {
    setMessage(error.message);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatDate(value) {
  if (!value) return "Sin fecha";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" });
}

function formatRelativeOrDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const minutes = Math.floor((Date.now() - date.getTime()) / 60000);
  if (minutes < 1) return "Ahora";
  if (minutes < 60) return `Hace ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `Hace ${hours} h`;
  return formatDate(value);
}

function toLocalInputValue(isoValue) {
  if (!isoValue) return "";
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function nowLocalInputValue() {
  return toLocalInputValue(new Date().toISOString());
}

function formatRemaining(account) {
  if (account.expired) return "Vencida";
  const days = account.days_remaining ?? 0;
  if (days > 1) return `Vence en ${days} días`;
  if (days === 1) return "Vence mañana";
  const hours = Math.ceil((account.seconds_remaining || 0) / 3600);
  return hours > 0 ? `Vence en ${hours} h` : "Vence pronto";
}

function urgencyOf(item) {
  return item.urgency || "red";
}

function matchesSearch(text, query) {
  return !query || String(text || "").toLowerCase().includes(query.toLowerCase());
}

function muted(text) {
  return `<p class="muted">${escapeHtml(text)}</p>`;
}

function actionButtons(id, editClass, deleteClass) {
  return `
    <div class="row-actions">
      <button type="button" class="secondary compact ${editClass}" data-id="${id}">Editar</button>
      <button type="button" class="danger compact ${deleteClass}" data-id="${id}">Eliminar</button>
    </div>`;
}

function cardHead(title, trailing) {
  return `<div class="card-head"><strong>${title}</strong>${trailing || ""}</div>`;
}

function urgencyBadge(item) {
  const tone = urgencyOf(item);
  return `<span class="badge ${tone}">${formatRemaining(item)}</span>`;
}

function miniCard(body, urgency) {
  const cls = urgency ? `mini-card urgency-${urgency}` : "mini-card";
  return `<article class="${cls}">${body}</article>`;
}

function listOrEmpty(items, mapFn, emptyText) {
  return items.length ? items.map(mapFn).join("") : muted(emptyText);
}

function selectedMainAccount() {
  const id = Number(accountMain.value);
  return id ? data.main_accounts.find((item) => item.id === id) || null : null;
}

function updateAliasPreview() {
  const main = selectedMainAccount();
  const email = accountEmail.value.trim().toLowerCase();
  if (main && email) {
    aliasPreview.textContent = `${email} → se busca en la bandeja de ${main.email} (sin cambiar el alias).`;
  } else if (main) {
    aliasPreview.textContent = `Escribe el alias exacto que das a los clientes (ej. cinecolred+bat@gmail.com). Los códigos se buscan en ${main.email}.`;
  } else {
    aliasPreview.textContent = "Sin cuenta principal: se usará el IMAP de .env y el correo que indiques.";
  }
}

function updateAssignmentUrgency() {
  const dateInput = document.querySelector("#assignment-date");
  if (!dateInput) return;
  dateInput.classList.remove("urgency-green", "urgency-yellow", "urgency-red");
  if (!dateInput.value) return;
  const assigned = new Date(dateInput.value);
  if (Number.isNaN(assigned.getTime())) return;
  const expires = new Date(assigned.getTime() + 30 * 24 * 60 * 60 * 1000);
  const days = Math.max(0, Math.ceil((expires - Date.now()) / (24 * 60 * 60 * 1000)));
  let urgency = "red";
  if (days > 20) urgency = "green";
  else if (days > 10) urgency = "yellow";
  dateInput.classList.add(`urgency-${urgency}`);
}

function setEditMode({ idField, titleEl, submitEl, cancelEl, createTitle, createSubmit, editTitle }) {
  document.querySelector(titleEl).textContent = editTitle;
  document.querySelector(submitEl).textContent = "Guardar cambios";
  document.querySelector(cancelEl).hidden = false;
}

function resetEntityForm({
  idField, form, titleEl, submitEl, cancelEl, createTitle, createSubmit, after,
}) {
  document.querySelector(idField).value = "";
  document.querySelector(form).reset();
  document.querySelector(titleEl).textContent = createTitle;
  document.querySelector(submitEl).textContent = createSubmit;
  document.querySelector(cancelEl).hidden = true;
  after?.();
}

function resetMainForm() {
  resetEntityForm({
    idField: "#main-edit-id",
    form: "#main-account-form",
    titleEl: "#main-form-title",
    submitEl: "#main-submit",
    cancelEl: "#main-cancel-edit",
    createTitle: "Agregar cuenta principal",
    createSubmit: "Agregar cuenta principal",
    after: () => {
      document.querySelector("#main-imap-host").value = "imap.gmail.com";
      document.querySelector("#main-imap-port").value = "993";
      document.querySelector("#main-imap-folder").value = "INBOX";
      document.querySelector("#main-domain").value = "gmail.com";
      document.querySelector("#main-password").required = true;
      document.querySelector("#main-password").placeholder = "Obligatoria al crear";
    },
  });
}

function resetAccountForm() {
  resetEntityForm({
    idField: "#account-edit-id",
    form: "#account-form",
    titleEl: "#account-form-title",
    submitEl: "#account-submit",
    cancelEl: "#account-cancel-edit",
    createTitle: "Agregar cuenta de streaming",
    createSubmit: "Agregar cuenta",
    after: () => {
      accountPassword.required = true;
      accountPassword.placeholder = "Obligatoria al crear";
      updateAliasPreview();
    },
  });
}

function resetClientForm() {
  resetEntityForm({
    idField: "#client-edit-id",
    form: "#client-form",
    titleEl: "#client-form-title",
    submitEl: "#client-submit",
    cancelEl: "#client-cancel-edit",
    createTitle: "Agregar cliente",
    createSubmit: "Agregar cliente",
  });
}

function fillMainForm(account) {
  showPanel("main");
  document.querySelector("#main-edit-id").value = account.id;
  document.querySelector("#main-name").value = account.name;
  document.querySelector("#main-email").value = account.email;
  document.querySelector("#main-password").value = "";
  document.querySelector("#main-password").required = false;
  document.querySelector("#main-password").placeholder = "Dejar vacío para no cambiar";
  document.querySelector("#main-domain").value = account.domain;
  document.querySelector("#main-imap-host").value = account.imap_host;
  document.querySelector("#main-imap-port").value = account.imap_port;
  document.querySelector("#main-imap-folder").value = account.imap_folder;
  setEditMode({
    titleEl: "#main-form-title",
    submitEl: "#main-submit",
    cancelEl: "#main-cancel-edit",
    editTitle: "Editar cuenta principal",
  });
}

function fillAccountForm(account) {
  showPanel("streaming");
  document.querySelector("#account-edit-id").value = account.id;
  accountPlatform.value = account.platform;
  accountMain.value = account.main_account_id || "";
  accountEmail.value = account.email;
  document.querySelector("#account-name").value = account.name;
  accountPassword.value = "";
  accountPassword.required = false;
  accountPassword.placeholder = "Dejar vacío para no cambiar";
  document.querySelector("#account-expires").value = toLocalInputValue(account.expires_at);
  setEditMode({
    titleEl: "#account-form-title",
    submitEl: "#account-submit",
    cancelEl: "#account-cancel-edit",
    editTitle: "Editar cuenta de streaming",
  });
  updateAliasPreview();
}

function fillClientForm(client) {
  showPanel("clients");
  document.querySelector("#client-edit-id").value = client.id;
  document.querySelector("#client-name").value = client.name;
  document.querySelector("#client-phone").value = client.phone;
  setEditMode({
    titleEl: "#client-form-title",
    submitEl: "#client-submit",
    cancelEl: "#client-cancel-edit",
    editTitle: "Editar cliente",
  });
}

function render() {
  const previousMain = accountMain.value;
  const summary = data.summary || {
    main_accounts: 0,
    streaming_accounts: 0,
    clients: 0,
    assignments: 0,
    urgency: { green: 0, yellow: 0, red: 0 },
    expiring_soon: [],
  };

  document.querySelector("#summary-stats").innerHTML = [
    ["Principales", summary.main_accounts],
    ["Streaming", summary.streaming_accounts],
    ["Clientes", summary.clients],
    ["Asociaciones", summary.assignments],
    ["Verde +20", summary.urgency.green, "green"],
    ["Amarillo -20", summary.urgency.yellow, "yellow"],
    ["Rojo -10", summary.urgency.red, "red"],
  ].map(([label, value, tone]) =>
    `<article class="stat-card${tone ? ` ${tone}` : ""}"><small>${label}</small><strong>${value}</strong></article>`
  ).join("");

  document.querySelector("#expiring-list").innerHTML = listOrEmpty(
    summary.expiring_soon,
    (account) => miniCard(`
      ${cardHead(`${escapeHtml(account.platform)} · ${escapeHtml(account.name)}`, urgencyBadge(account))}
      <span>${escapeHtml(account.email)}</span>
      <small>Vence: ${escapeHtml(formatDate(account.expires_at))}</small>
    `, account.urgency),
    "No hay cuentas por vencer pronto. Todo en verde."
  );

  const events = data.audit || [];
  document.querySelector("#audit-list").innerHTML = listOrEmpty(
    events,
    (event) => {
      const meta = AUDIT_LABELS[event.action] || { label: event.action, tone: "muted" };
      const detail = [event.detail, event.target ? `ID ${event.target}` : null, event.ip_address].filter(Boolean);
      return `
        <article class="audit-row audit-${meta.tone}">
          <span class="audit-dot" aria-hidden="true"></span>
          <div class="audit-body">
            <div class="audit-top">
              <span class="audit-label">${escapeHtml(meta.label)}</span>
              <time class="audit-time" title="${escapeHtml(formatDate(event.created_at))}">${formatRelativeOrDate(event.created_at)}</time>
            </div>
            <p class="audit-actor">${escapeHtml(event.actor || "—")}</p>
            ${detail.length ? `<p class="audit-meta">${escapeHtml(detail.join(" · "))}</p>` : ""}
          </div>
        </article>`;
    },
    "Aún no hay actividad registrada."
  );

  const mainQuery = document.querySelector("#main-search")?.value || "";
  const filteredMains = data.main_accounts.filter((a) =>
    matchesSearch(`${a.name} ${a.email} ${a.domain}`, mainQuery)
  );
  document.querySelector("#main-accounts-list").innerHTML = listOrEmpty(
    filteredMains,
    (account) => miniCard(`
      ${cardHead(escapeHtml(account.name), actionButtons(account.id, "edit-main", "delete-main"))}
      <span>${escapeHtml(account.email)}</span>
      <small>Dominio: *@${escapeHtml(account.domain)}</small>
      <small>${escapeHtml(account.imap_host)}:${account.imap_port} · ${escapeHtml(account.imap_folder)}</small>
      <small>${account.linked_accounts} cuenta(s) de streaming vinculadas</small>
      <label class="renew-label" for="main-pass-${account.id}">Contraseña de aplicación IMAP</label>
      <div class="renew-row">
        <input id="main-pass-${account.id}" type="password" placeholder="xxxx xxxx xxxx xxxx" autocomplete="new-password">
        <button type="button" class="secondary compact main-pass-button" data-main-id="${account.id}">Guardar</button>
      </div>
    `),
    "No hay cuentas principales todavía."
  );

  accountMain.innerHTML = '<option value="">Usar IMAP de .env</option>' + data.main_accounts
    .map((a) => `<option value="${a.id}">${escapeHtml(a.name)} · ${escapeHtml(a.email)}</option>`)
    .join("");
  if (previousMain) accountMain.value = previousMain;

  const accountQuery = document.querySelector("#account-search")?.value || "";
  const filteredAccounts = data.accounts.filter((a) =>
    matchesSearch(`${a.name} ${a.email} ${a.platform}`, accountQuery)
  );
  document.querySelector("#accounts-list").innerHTML = listOrEmpty(
    filteredAccounts,
    (account) => {
      const tone = urgencyOf(account);
      return `<article class="mini-card urgency-${tone}${account.expired ? " expired" : ""}">
        ${cardHead(escapeHtml(account.name), urgencyBadge(account))}
        <span>${escapeHtml(account.platform)} · ${escapeHtml(account.email)}</span>
        <small>${account.main_account_name
          ? `Bandeja: ${escapeHtml(account.main_account_name)}`
          : "Bandeja: IMAP de .env"}</small>
        <small>Vence: ${escapeHtml(formatDate(account.expires_at))}</small>
        <label class="renew-label" for="renew-${account.id}">Renovar hasta</label>
        <div class="renew-row">
          <input id="renew-${account.id}" type="datetime-local" value="${toLocalInputValue(account.expires_at)}">
          <button type="button" class="secondary compact renew-button" data-account-id="${account.id}">Actualizar</button>
        </div>
        ${actionButtons(account.id, "edit-account", "delete-account")}
      </article>`;
    },
    "No hay cuentas todavía."
  );

  const clientQuery = document.querySelector("#client-search")?.value || "";
  const filteredClients = data.clients.filter((c) => matchesSearch(`${c.name} ${c.phone}`, clientQuery));
  document.querySelector("#clients-list").innerHTML = listOrEmpty(
    filteredClients,
    (client) => {
      const assignments = client.assignments.length
        ? client.assignments.map((item) => `
            <div class="assignment-row urgency-${urgencyOf(item)}">
              <strong>${escapeHtml(item.platform)}: ${escapeHtml(item.name)}</strong>
              <span>${escapeHtml(item.email || "Sin correo")}</span>
              <small>Asociación: ${escapeHtml(formatDate(item.assigned_at))}</small>
              <small>Acceso hasta: ${escapeHtml(formatDate(item.expires_at))}</small>
              ${urgencyBadge(item)}
              <button type="button" class="danger compact unassign-button" data-client-id="${client.id}" data-account-id="${item.account_id}">Quitar</button>
            </div>`).join("")
        : muted("Sin cuentas asociadas");
      return miniCard(`
        ${cardHead(escapeHtml(client.name), actionButtons(client.id, "edit-client", "delete-client"))}
        <span>${escapeHtml(client.phone)}</span>
        ${assignments}
      `);
    },
    "No hay clientes todavía."
  );

  const assignmentQuery = document.querySelector("#assignment-search")?.value || "";
  const filteredAssignments = (data.assignments || []).filter((item) =>
    matchesSearch(`${item.client_name} ${item.client_phone} ${item.account_name} ${item.account_email} ${item.platform}`, assignmentQuery)
  );
  document.querySelector("#assignments-list").innerHTML = listOrEmpty(
    filteredAssignments,
    (item) => miniCard(`
      ${cardHead(escapeHtml(item.client_name), urgencyBadge(item))}
      <span>${escapeHtml(item.client_phone)}</span>
      <small>${escapeHtml(item.platform)}: ${escapeHtml(item.account_name)} · ${escapeHtml(item.account_email)}</small>
      <small>Asociación: ${escapeHtml(formatDate(item.assigned_at))}</small>
      <small>Acceso hasta: ${escapeHtml(formatDate(item.expires_at))}</small>
      <div class="row-actions">
        <button type="button" class="danger compact unassign-button" data-client-id="${item.client_id}" data-account-id="${item.account_id}">Quitar</button>
      </div>
    `, urgencyOf(item)),
    "Aún no hay asociaciones."
  );

  assignmentClient.innerHTML = '<option value="">Cliente</option>' + data.clients
    .map((c) => `<option value="${c.id}">${escapeHtml(c.name)} · ${escapeHtml(c.phone)}</option>`).join("");
  assignmentAccount.innerHTML = '<option value="">Cuenta</option>' + data.accounts
    .map((a) => `<option value="${a.id}">${escapeHtml(a.platform)} · ${escapeHtml(a.name)} · ${escapeHtml(a.email)} · ${formatRemaining(a)}</option>`).join("");

  const assignmentDate = document.querySelector("#assignment-date");
  if (assignmentDate && !assignmentDate.value) assignmentDate.value = nowLocalInputValue();
  updateAssignmentUrgency();
  updateAliasPreview();
  renderShop();
}

function formatCopAdmin(amount) {
  return `$${Number(amount || 0).toLocaleString("es-CO")}`;
}

function platformLabel(key) {
  if (!key) return null;
  return (data.platforms || []).find((p) => p.key === key)?.label || key;
}

function shopData() {
  return data.shop || { products: [], combos: [], discounts: [], stock: [], payments: [], summary: {} };
}

function showShopTab(tab) {
  shopTab = tab;
  document.querySelectorAll(".shop-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.shopTab === tab);
  });
  document.querySelectorAll(".shop-admin-pane").forEach((pane) => {
    const active = pane.dataset.shopTab === tab;
    pane.hidden = !active;
    pane.classList.toggle("active", active);
  });
}

function renderComboItemChecks(selected = {}) {
  const box = document.querySelector("#shop-combo-items");
  if (!box) return;
  const products = shopData().products || [];
  box.innerHTML = products.length
    ? products.map((product) => {
        const checked = selected[product.id] ? "checked" : "";
        const qty = selected[product.id] || 1;
        return `
          <label class="combo-item-row">
            <input type="checkbox" class="combo-product-check" value="${product.id}" ${checked}>
            <span>${escapeHtml(product.label)} · ${formatCopAdmin(product.price_cop)}</span>
            <input type="number" class="combo-product-qty" data-product-id="${product.id}" min="1" max="20" value="${qty}">
          </label>`;
      }).join("")
    : muted("Primero crea productos.");
}

function selectedComboItems() {
  return [...document.querySelectorAll(".combo-product-check:checked")].map((check) => {
    const qtyInput = document.querySelector(`.combo-product-qty[data-product-id="${check.value}"]`);
    return {
      product_id: Number(check.value),
      quantity: Math.max(1, Number(qtyInput?.value || 1)),
    };
  });
}

function resetShopProductForm() {
  resetEntityForm({
    idField: "#shop-product-edit-id",
    form: "#shop-product-form",
    titleEl: "#shop-product-form-title",
    submitEl: "#shop-product-submit",
    cancelEl: "#shop-product-cancel",
    createTitle: "Agregar producto",
    createSubmit: "Agregar producto",
    after: () => {
      document.querySelector("#shop-product-category").value = "Streaming";
      document.querySelector("#shop-product-active").value = "1";
      document.querySelector("#shop-product-key").disabled = false;
      document.querySelector("#shop-product-otp-senders").value = "";
    },
  });
}

function resetShopComboForm() {
  resetEntityForm({
    idField: "#shop-combo-edit-id",
    form: "#shop-combo-form",
    titleEl: "#shop-combo-form-title",
    submitEl: "#shop-combo-submit",
    cancelEl: "#shop-combo-cancel",
    createTitle: "Agregar combo",
    createSubmit: "Agregar combo",
    after: () => {
      document.querySelector("#shop-combo-active").value = "1";
      document.querySelector("#shop-combo-key").disabled = false;
      renderComboItemChecks();
    },
  });
}

function resetShopDiscountForm() {
  resetEntityForm({
    idField: "#shop-discount-edit-id",
    form: "#shop-discount-form",
    titleEl: "#shop-discount-form-title",
    submitEl: "#shop-discount-submit",
    cancelEl: "#shop-discount-cancel",
    createTitle: "Agregar descuento",
    createSubmit: "Agregar descuento",
    after: () => {
      document.querySelector("#shop-discount-type").value = "percent";
      document.querySelector("#shop-discount-active").value = "1";
      document.querySelector("#shop-discount-code").disabled = false;
    },
  });
}

function resetShopPaymentForm() {
  resetEntityForm({
    idField: "#shop-payment-edit-id",
    form: "#shop-payment-form",
    titleEl: "#shop-payment-form-title",
    submitEl: "#shop-payment-submit",
    cancelEl: "#shop-payment-cancel",
    createTitle: "Agregar forma de pago",
    createSubmit: "Agregar forma de pago",
    after: () => {
      document.querySelector("#shop-payment-active").value = "1";
    },
  });
}

function resetShopStockForm() {
  resetEntityForm({
    idField: "#shop-stock-edit-id",
    form: "#shop-stock-form",
    titleEl: "#shop-stock-form-title",
    submitEl: "#shop-stock-submit",
    cancelEl: "#shop-stock-cancel",
    createTitle: "Agregar cuenta en stock",
    createSubmit: "Agregar cuenta",
    after: () => {
      document.querySelector("#shop-stock-status").value = "available";
      document.querySelector("#shop-stock-password").required = true;
      document.querySelector("#shop-stock-password").placeholder = "Obligatoria al crear";
      fillShopStockProductSelect();
    },
  });
}

function fillShopStockProductSelect(selectedId = "") {
  const select = document.querySelector("#shop-stock-product");
  if (!select) return;
  select.innerHTML = '<option value="">Selecciona producto</option>' + (shopData().products || [])
    .map((p) => `<option value="${p.id}">${escapeHtml(p.label)}</option>`)
    .join("");
  if (selectedId) select.value = String(selectedId);
}

function renderShop() {
  const shop = shopData();
  const summary = shop.summary || {};
  const stats = document.querySelector("#shop-summary-stats");
  if (stats) {
    stats.innerHTML = [
      ["Productos", summary.products || 0],
      ["Activos", summary.active_products || 0],
      ["Combos", summary.combos || 0],
      ["Cupones", summary.discounts || 0],
      ["Stock disponible", summary.stock_available || 0, "green"],
      ["Stock total", summary.stock_total || 0],
    ].map(([label, value, tone]) =>
      `<article class="stat-card${tone ? ` ${tone}` : ""}"><small>${label}</small><strong>${value}</strong></article>`
    ).join("");
  }

  const categories = [...new Set((shop.products || []).map((p) => p.category).filter(Boolean))];
  const datalist = document.querySelector("#shop-category-list");
  if (datalist) {
    datalist.innerHTML = categories.map((c) => `<option value="${escapeHtml(c)}"></option>`).join("");
  }

  const productQuery = document.querySelector("#shop-product-search")?.value || "";
  const products = (shop.products || []).filter((p) =>
    matchesSearch(`${p.label} ${p.key} ${p.category} ${p.blurb}`, productQuery)
  );
  document.querySelector("#shop-products-list").innerHTML = listOrEmpty(
    products,
    (product) => {
      const otp = product.otp_senders
        ? `OTP: ${escapeHtml(product.otp_senders)}`
        : "Sin remitentes OTP";
      return miniCard(`
        ${cardHead(escapeHtml(product.label), `<span class="badge ${product.active ? "green" : "red"}">${product.active ? "Activo" : "Oculto"}</span>`)}
        <span class="shop-price-line">${formatCopAdmin(product.price_cop)} · ${escapeHtml(product.category)}</span>
        <small>${escapeHtml(product.blurb || "Sin descripción")} · clave ${escapeHtml(product.key)}</small>
        <small>${otp}</small>
        <small>Stock disponible: ${product.stock_available || 0}</small>
        ${actionButtons(product.id, "edit-shop-product", "delete-shop-product")}
      `);
    },
    "No hay productos en el catálogo."
  );

  if (!document.querySelector("#shop-combo-edit-id")?.value) {
    renderComboItemChecks();
  }

  const comboQuery = document.querySelector("#shop-combo-search")?.value || "";
  const combos = (shop.combos || []).filter((c) =>
    matchesSearch(`${c.label} ${c.key} ${c.blurb}`, comboQuery)
  );
  document.querySelector("#shop-combos-list").innerHTML = listOrEmpty(
    combos,
    (combo) => {
      const items = (combo.items || []).map((i) => `${i.label} x${i.quantity}`).join(", ") || "Sin ítems";
      return miniCard(`
        ${cardHead(escapeHtml(combo.label), `<span class="badge ${combo.active ? "green" : "red"}">${combo.active ? "Activo" : "Oculto"}</span>`)}
        <span class="shop-price-line">${formatCopAdmin(combo.price_cop)}</span>
        <small>${escapeHtml(combo.blurb || "")}</small>
        <small>${escapeHtml(items)}</small>
        ${actionButtons(combo.id, "edit-shop-combo", "delete-shop-combo")}
      `);
    },
    "No hay combos todavía."
  );

  const discountQuery = document.querySelector("#shop-discount-search")?.value || "";
  const discounts = (shop.discounts || []).filter((d) =>
    matchesSearch(`${d.code} ${d.label}`, discountQuery)
  );
  document.querySelector("#shop-discounts-list").innerHTML = listOrEmpty(
    discounts,
    (discount) => {
      const valueLabel = discount.discount_type === "percent"
        ? `${discount.value}%`
        : formatCopAdmin(discount.value);
      return miniCard(`
        ${cardHead(escapeHtml(discount.code), `<span class="badge ${discount.active ? "green" : "red"}">${discount.active ? "Activo" : "Inactivo"}</span>`)}
        <span>${escapeHtml(discount.label)} · ${valueLabel}</span>
        <small>${discount.expires_at ? `Vence: ${escapeHtml(formatDate(discount.expires_at))}` : "Sin vencimiento"}</small>
        ${actionButtons(discount.id, "edit-shop-discount", "delete-shop-discount")}
      `);
    },
    "No hay cupones todavía."
  );

  const paymentQuery = document.querySelector("#shop-payment-search")?.value || "";
  const payments = (shop.payments || []).filter((method) =>
    matchesSearch(`${method.label} ${method.key_value} ${method.instructions}`, paymentQuery)
  );
  document.querySelector("#shop-payments-list").innerHTML = listOrEmpty(
    payments,
    (method) => miniCard(`
      ${cardHead(escapeHtml(method.label), `<span class="badge ${method.active ? "green" : "red"}">${method.active ? "Activa" : "Oculta"}</span>`)}
      <span>${escapeHtml(method.detail_label || "Dato")}: ${escapeHtml(method.key_value)}</span>
      <small>${escapeHtml(method.instructions || "Sin instrucciones")}</small>
      ${actionButtons(method.id, "edit-shop-payment", "delete-shop-payment")}
    `),
    "No hay formas de pago todavía."
  );

  fillShopStockProductSelect(document.querySelector("#shop-stock-product")?.value || "");
  const stockQuery = document.querySelector("#shop-stock-search")?.value || "";
  const stock = (shop.stock || []).filter((s) =>
    matchesSearch(`${s.login} ${s.product_label} ${s.status} ${s.notes}`, stockQuery)
  );
  const statusLabel = { available: "Disponible", reserved: "Reservada", sold: "Vendida" };
  document.querySelector("#shop-stock-list").innerHTML = listOrEmpty(
    stock,
    (item) => miniCard(`
      ${cardHead(escapeHtml(item.product_label), `<span class="badge ${item.on_duty ? "green" : item.status === "available" ? "yellow" : "red"}">${item.on_duty ? "En turno" : (statusLabel[item.status] || item.status)}</span>`)}
      <span>${escapeHtml(item.login)}</span>
      <small>Se entrega en 2 pagos y luego pasa a la siguiente. Lleva ${item.sale_count || 0}.</small>
      <small>Pass: ${escapeHtml(item.password || "—")}</small>
      <small>${escapeHtml(item.notes || "Sin notas")}</small>
      ${actionButtons(item.id, "edit-shop-stock", "delete-shop-stock")}
    `),
    "No hay cuentas en stock."
  );

  showShopTab(shopTab);
}

function fillShopProductForm(product) {
  showPanel("shop");
  showShopTab("products");
  document.querySelector("#shop-product-edit-id").value = product.id;
  document.querySelector("#shop-product-label").value = product.label;
  document.querySelector("#shop-product-key").value = product.key;
  document.querySelector("#shop-product-key").disabled = true;
  document.querySelector("#shop-product-price").value = product.price_cop;
  document.querySelector("#shop-product-category").value = product.category;
  document.querySelector("#shop-product-blurb").value = product.blurb || "";
  document.querySelector("#shop-product-active").value = product.active ? "1" : "0";
  document.querySelector("#shop-product-otp-senders").value = product.otp_senders || "";
  setEditMode({
    titleEl: "#shop-product-form-title",
    submitEl: "#shop-product-submit",
    cancelEl: "#shop-product-cancel",
    editTitle: "Editar producto",
  });
}

function fillShopComboForm(combo) {
  showPanel("shop");
  showShopTab("combos");
  document.querySelector("#shop-combo-edit-id").value = combo.id;
  document.querySelector("#shop-combo-label").value = combo.label;
  document.querySelector("#shop-combo-key").value = combo.key;
  document.querySelector("#shop-combo-key").disabled = true;
  document.querySelector("#shop-combo-price").value = combo.price_cop;
  document.querySelector("#shop-combo-blurb").value = combo.blurb || "";
  document.querySelector("#shop-combo-active").value = combo.active ? "1" : "0";
  const selected = {};
  (combo.items || []).forEach((item) => { selected[item.product_id] = item.quantity; });
  renderComboItemChecks(selected);
  setEditMode({
    titleEl: "#shop-combo-form-title",
    submitEl: "#shop-combo-submit",
    cancelEl: "#shop-combo-cancel",
    editTitle: "Editar combo",
  });
}

function fillShopDiscountForm(discount) {
  showPanel("shop");
  showShopTab("discounts");
  document.querySelector("#shop-discount-edit-id").value = discount.id;
  document.querySelector("#shop-discount-code").value = discount.code;
  document.querySelector("#shop-discount-code").disabled = true;
  document.querySelector("#shop-discount-label").value = discount.label;
  document.querySelector("#shop-discount-type").value = discount.discount_type;
  document.querySelector("#shop-discount-value").value = discount.value;
  document.querySelector("#shop-discount-expires").value = toLocalInputValue(discount.expires_at);
  document.querySelector("#shop-discount-active").value = discount.active ? "1" : "0";
  setEditMode({
    titleEl: "#shop-discount-form-title",
    submitEl: "#shop-discount-submit",
    cancelEl: "#shop-discount-cancel",
    editTitle: "Editar descuento",
  });
}

function fillShopPaymentForm(method) {
  showPanel("shop");
  showShopTab("payments");
  document.querySelector("#shop-payment-edit-id").value = method.id;
  document.querySelector("#shop-payment-label").value = method.label;
  document.querySelector("#shop-payment-detail").value = method.detail_label || "";
  document.querySelector("#shop-payment-key").value = method.key_value;
  document.querySelector("#shop-payment-instructions").value = method.instructions || "";
  document.querySelector("#shop-payment-active").value = method.active ? "1" : "0";
  setEditMode({
    titleEl: "#shop-payment-form-title",
    submitEl: "#shop-payment-submit",
    cancelEl: "#shop-payment-cancel",
    editTitle: "Editar forma de pago",
  });
}

function fillShopStockForm(item) {
  showPanel("shop");
  showShopTab("stock");
  document.querySelector("#shop-stock-edit-id").value = item.id;
  fillShopStockProductSelect(item.product_id);
  document.querySelector("#shop-stock-login").value = item.login;
  document.querySelector("#shop-stock-password").value = "";
  document.querySelector("#shop-stock-password").required = false;
  document.querySelector("#shop-stock-password").placeholder = "Dejar vacío para no cambiar";
  document.querySelector("#shop-stock-status").value = item.status;
  document.querySelector("#shop-stock-notes").value = item.notes || "";
  setEditMode({
    titleEl: "#shop-stock-form-title",
    submitEl: "#shop-stock-submit",
    cancelEl: "#shop-stock-cancel",
    editTitle: "Editar cuenta en stock",
  });
}

async function loadPlatformOptions() {
  const previous = accountPlatform.value;
  const platforms = data.platforms?.length
    ? data.platforms
    : await apiRequest("/api/platforms");
  accountPlatform.innerHTML = '<option value="">Selecciona un producto</option>';
  platforms.forEach(({ key, label }) => {
    accountPlatform.add(new Option(label, key));
  });
  if (previous && [...accountPlatform.options].some((o) => o.value === previous)) {
    accountPlatform.value = previous;
  }
}

async function showDashboard() {
  data = await request("/api/admin/data");
  if (!data.shop) data.shop = { products: [], combos: [], discounts: [], stock: [], summary: {} };
  if (!data.platforms) data.platforms = [];
  await loadPlatformOptions();
  loginView.hidden = true;
  dashboard.hidden = false;
  document.body.classList.add("dashboard-open");
  render();
}

async function submitEntity({ editId, createUrl, updateUrl, payload, reset, okCreate, okUpdate }) {
  await runAction(async () => {
    if (editId) {
      await request(updateUrl, { method: "PUT", body: JSON.stringify(payload) });
      setMessage(okUpdate, true);
    } else {
      await request(createUrl, { method: "POST", body: JSON.stringify(payload) });
      setMessage(okCreate, true);
    }
    reset();
    await showDashboard();
  });
}

dashboard.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button || !dashboard.contains(button)) return;

  if (button.classList.contains("renew-button")) {
    const accountId = button.dataset.accountId;
    const input = document.querySelector(`#renew-${accountId}`);
    await runAction(async () => {
      await request(`/api/admin/accounts/${accountId}/expiration`, {
        method: "PATCH",
        body: JSON.stringify({ expires_at: new Date(input.value).toISOString() }),
      });
      setMessage("Fecha de vencimiento actualizada.", true);
      await showDashboard();
    });
    return;
  }

  if (button.classList.contains("main-pass-button")) {
    const mainId = button.dataset.mainId;
    const input = document.querySelector(`#main-pass-${mainId}`);
    await runAction(async () => {
      await request(`/api/admin/main-accounts/${mainId}/password`, {
        method: "PATCH",
        body: JSON.stringify({ password: input.value }),
      });
      input.value = "";
      setMessage("Contraseña IMAP de la cuenta principal actualizada.", true);
    });
    return;
  }

  if (button.classList.contains("edit-main")) {
    const account = data.main_accounts.find((item) => item.id === Number(button.dataset.id));
    if (account) fillMainForm(account);
    return;
  }
  if (button.classList.contains("edit-account")) {
    const account = data.accounts.find((item) => item.id === Number(button.dataset.id));
    if (account) fillAccountForm(account);
    return;
  }
  if (button.classList.contains("edit-client")) {
    const client = data.clients.find((item) => item.id === Number(button.dataset.id));
    if (client) fillClientForm(client);
    return;
  }
  if (button.classList.contains("edit-shop-product")) {
    const product = shopData().products.find((item) => item.id === Number(button.dataset.id));
    if (product) fillShopProductForm(product);
    return;
  }
  if (button.classList.contains("edit-shop-combo")) {
    const combo = shopData().combos.find((item) => item.id === Number(button.dataset.id));
    if (combo) fillShopComboForm(combo);
    return;
  }
  if (button.classList.contains("edit-shop-discount")) {
    const discount = shopData().discounts.find((item) => item.id === Number(button.dataset.id));
    if (discount) fillShopDiscountForm(discount);
    return;
  }
  if (button.classList.contains("edit-shop-payment")) {
    const method = (shopData().payments || []).find((item) => item.id === Number(button.dataset.id));
    if (method) fillShopPaymentForm(method);
    return;
  }
  if (button.classList.contains("edit-shop-stock")) {
    const item = shopData().stock.find((row) => row.id === Number(button.dataset.id));
    if (item) fillShopStockForm(item);
    return;
  }

  const deletes = [
    ["delete-main", "¿Eliminar esta cuenta principal?", `/api/admin/main-accounts/${button.dataset.id}`, resetMainForm, "Cuenta principal eliminada."],
    ["delete-account", "¿Eliminar esta cuenta de streaming y sus asociaciones?", `/api/admin/accounts/${button.dataset.id}`, resetAccountForm, "Cuenta eliminada."],
    ["delete-client", "¿Eliminar este cliente y sus asociaciones?", `/api/admin/clients/${button.dataset.id}`, resetClientForm, "Cliente eliminado."],
    ["delete-shop-product", "¿Eliminar este producto del catálogo?", `/api/admin/shop/products/${button.dataset.id}`, resetShopProductForm, "Producto eliminado."],
    ["delete-shop-combo", "¿Eliminar este combo?", `/api/admin/shop/combos/${button.dataset.id}`, resetShopComboForm, "Combo eliminado."],
    ["delete-shop-discount", "¿Eliminar este cupón?", `/api/admin/shop/discounts/${button.dataset.id}`, resetShopDiscountForm, "Descuento eliminado."],
    ["delete-shop-payment", "¿Eliminar esta forma de pago?", `/api/admin/shop/payments/${button.dataset.id}`, resetShopPaymentForm, "Forma de pago eliminada."],
    ["delete-shop-stock", "¿Eliminar esta cuenta del stock?", `/api/admin/shop/stock/${button.dataset.id}`, resetShopStockForm, "Cuenta de stock eliminada."],
  ];
  for (const [cls, confirmText, url, reset, ok] of deletes) {
    if (!button.classList.contains(cls)) continue;
    if (!window.confirm(confirmText)) return;
    await runAction(async () => {
      await request(url, { method: "DELETE" });
      reset();
      setMessage(ok, true);
      await showDashboard();
    });
    return;
  }

  if (button.classList.contains("unassign-button")) {
    if (!window.confirm("¿Quitar esta asociación?")) return;
    await runAction(async () => {
      await request(`/api/admin/assignments/${button.dataset.clientId}/${button.dataset.accountId}`, { method: "DELETE" });
      setMessage("Asociación eliminada.", true);
      await showDashboard();
    });
  }
});

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => showPanel(button.dataset.panel));
});

document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await request("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({
        email: document.querySelector("#admin-email").value,
        password: document.querySelector("#admin-password").value,
      }),
    });
    await showDashboard();
  } catch (error) {
    loginMessage.textContent = error.message;
  }
});

document.querySelector("#main-cancel-edit").addEventListener("click", resetMainForm);
document.querySelector("#account-cancel-edit").addEventListener("click", resetAccountForm);
document.querySelector("#client-cancel-edit").addEventListener("click", resetClientForm);
document.querySelector("#shop-product-cancel")?.addEventListener("click", resetShopProductForm);
document.querySelector("#shop-combo-cancel")?.addEventListener("click", resetShopComboForm);
document.querySelector("#shop-discount-cancel")?.addEventListener("click", resetShopDiscountForm);
document.querySelector("#shop-payment-cancel")?.addEventListener("click", resetShopPaymentForm);
document.querySelector("#shop-stock-cancel")?.addEventListener("click", resetShopStockForm);

document.querySelectorAll(".shop-tab").forEach((button) => {
  button.addEventListener("click", () => showShopTab(button.dataset.shopTab));
});

document.querySelector("#main-account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const editId = document.querySelector("#main-edit-id").value;
  await submitEntity({
    editId,
    createUrl: "/api/admin/main-accounts",
    updateUrl: `/api/admin/main-accounts/${editId}`,
    payload: {
      name: document.querySelector("#main-name").value,
      email: document.querySelector("#main-email").value,
      password: document.querySelector("#main-password").value,
      domain: document.querySelector("#main-domain").value,
      imap_host: document.querySelector("#main-imap-host").value,
      imap_port: Number(document.querySelector("#main-imap-port").value),
      imap_folder: document.querySelector("#main-imap-folder").value,
    },
    reset: resetMainForm,
    okCreate: "Cuenta principal agregada.",
    okUpdate: "Cuenta principal actualizada.",
  });
});

document.querySelector("#account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const editId = document.querySelector("#account-edit-id").value;
  await submitEntity({
    editId,
    createUrl: "/api/admin/accounts",
    updateUrl: `/api/admin/accounts/${editId}`,
    payload: {
      platform: accountPlatform.value,
      name: document.querySelector("#account-name").value,
      email: accountEmail.value,
      password: accountPassword.value,
      expires_at: new Date(document.querySelector("#account-expires").value).toISOString(),
      main_account_id: accountMain.value ? Number(accountMain.value) : null,
      subdomain: "",
    },
    reset: resetAccountForm,
    okCreate: "Cuenta agregada.",
    okUpdate: "Cuenta actualizada.",
  });
});

document.querySelector("#client-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const editId = document.querySelector("#client-edit-id").value;
  await submitEntity({
    editId,
    createUrl: "/api/admin/clients",
    updateUrl: `/api/admin/clients/${editId}`,
    payload: {
      name: document.querySelector("#client-name").value,
      phone: document.querySelector("#client-phone").value,
    },
    reset: resetClientForm,
    okCreate: "Cliente agregado.",
    okUpdate: "Cliente actualizado.",
  });
});

document.querySelector("#assignment-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await runAction(async () => {
    await request("/api/admin/assignments", {
      method: "POST",
      body: JSON.stringify({
        client_id: Number(assignmentClient.value),
        account_id: Number(assignmentAccount.value),
        assigned_at: new Date(document.querySelector("#assignment-date").value).toISOString(),
      }),
    });
    setMessage("Cuenta asociada.", true);
    document.querySelector("#assignment-date").value = nowLocalInputValue();
    await showDashboard();
  });
});

document.querySelector("#shop-product-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const editId = document.querySelector("#shop-product-edit-id").value;
  await submitEntity({
    editId,
    createUrl: "/api/admin/shop/products",
    updateUrl: `/api/admin/shop/products/${editId}`,
    payload: {
      key: document.querySelector("#shop-product-key").value,
      label: document.querySelector("#shop-product-label").value,
      price_cop: Number(document.querySelector("#shop-product-price").value),
      blurb: document.querySelector("#shop-product-blurb").value,
      category: document.querySelector("#shop-product-category").value,
      active: document.querySelector("#shop-product-active").value === "1",
      otp_senders: document.querySelector("#shop-product-otp-senders").value,
      otp_subjects: "",
    },
    reset: resetShopProductForm,
    okCreate: "Producto agregado.",
    okUpdate: "Producto actualizado.",
  });
});

document.querySelector("#shop-combo-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const items = selectedComboItems();
  if (!items.length) {
    setMessage("Selecciona al menos un producto para el combo.");
    return;
  }
  const editId = document.querySelector("#shop-combo-edit-id").value;
  await submitEntity({
    editId,
    createUrl: "/api/admin/shop/combos",
    updateUrl: `/api/admin/shop/combos/${editId}`,
    payload: {
      key: document.querySelector("#shop-combo-key").value,
      label: document.querySelector("#shop-combo-label").value,
      price_cop: Number(document.querySelector("#shop-combo-price").value),
      blurb: document.querySelector("#shop-combo-blurb").value,
      active: document.querySelector("#shop-combo-active").value === "1",
      items,
    },
    reset: resetShopComboForm,
    okCreate: "Combo agregado.",
    okUpdate: "Combo actualizado.",
  });
});

document.querySelector("#shop-discount-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const editId = document.querySelector("#shop-discount-edit-id").value;
  const expiresRaw = document.querySelector("#shop-discount-expires").value;
  await submitEntity({
    editId,
    createUrl: "/api/admin/shop/discounts",
    updateUrl: `/api/admin/shop/discounts/${editId}`,
    payload: {
      code: document.querySelector("#shop-discount-code").value,
      label: document.querySelector("#shop-discount-label").value,
      discount_type: document.querySelector("#shop-discount-type").value,
      value: Number(document.querySelector("#shop-discount-value").value),
      active: document.querySelector("#shop-discount-active").value === "1",
      expires_at: expiresRaw ? new Date(expiresRaw).toISOString() : null,
    },
    reset: resetShopDiscountForm,
    okCreate: "Descuento agregado.",
    okUpdate: "Descuento actualizado.",
  });
});

document.querySelector("#shop-payment-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const editId = document.querySelector("#shop-payment-edit-id").value;
  await submitEntity({
    editId,
    createUrl: "/api/admin/shop/payments",
    updateUrl: `/api/admin/shop/payments/${editId}`,
    payload: {
      label: document.querySelector("#shop-payment-label").value,
      detail_label: document.querySelector("#shop-payment-detail").value || "Llave",
      key_value: document.querySelector("#shop-payment-key").value,
      instructions: document.querySelector("#shop-payment-instructions").value,
      active: document.querySelector("#shop-payment-active").value === "1",
    },
    reset: resetShopPaymentForm,
    okCreate: "Forma de pago agregada.",
    okUpdate: "Forma de pago actualizada.",
  });
});

document.querySelector("#shop-stock-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const editId = document.querySelector("#shop-stock-edit-id").value;
  await submitEntity({
    editId,
    createUrl: "/api/admin/shop/stock",
    updateUrl: `/api/admin/shop/stock/${editId}`,
    payload: {
      product_id: Number(document.querySelector("#shop-stock-product").value),
      login: document.querySelector("#shop-stock-login").value,
      password: document.querySelector("#shop-stock-password").value,
      notes: document.querySelector("#shop-stock-notes").value,
      status: document.querySelector("#shop-stock-status").value,
    },
    reset: resetShopStockForm,
    okCreate: "Cuenta agregada al stock.",
    okUpdate: "Cuenta de stock actualizada.",
  });
});

document.querySelector("#logout-button").addEventListener("click", async () => {
  await request("/api/admin/logout", { method: "POST" });
  dashboard.hidden = true;
  loginView.hidden = false;
  document.body.classList.remove("dashboard-open");
});

accountMain.addEventListener("change", updateAliasPreview);
accountEmail.addEventListener("input", updateAliasPreview);
assignmentAccount.addEventListener("change", updateAssignmentUrgency);
document.querySelector("#assignment-date")?.addEventListener("change", updateAssignmentUrgency);
document.querySelector("#assignment-date")?.addEventListener("input", updateAssignmentUrgency);

[
  "#main-search",
  "#account-search",
  "#client-search",
  "#assignment-search",
  "#shop-product-search",
  "#shop-combo-search",
  "#shop-discount-search",
  "#shop-payment-search",
  "#shop-stock-search",
].forEach((selector) => {
  document.querySelector(selector)?.addEventListener("input", render);
});

loadPlatformOptions().catch(() => {});
