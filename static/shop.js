const CART_KEY = "centralcode_cart_v1";

const shopCatalog = document.querySelector("#shop-catalog");
const shopSearch = document.querySelector("#shop-search");
const shopCategory = document.querySelector("#shop-category");
const cartItemsEl = document.querySelector("#cart-items");
const cartEmpty = document.querySelector("#cart-empty");
const cartTotalEl = document.querySelector("#cart-total");
const cartBadge = document.querySelector("#cart-badge");
const checkoutOpen = document.querySelector("#checkout-open");
const checkoutModal = document.querySelector("#checkout-modal");
const checkoutClose = document.querySelector("#checkout-close");
const checkoutBackdrop = document.querySelector("#checkout-backdrop");
const checkoutForm = document.querySelector("#checkout-form");
const checkoutStatus = document.querySelector("#checkout-status");
const payAmount = document.querySelector("#pay-amount");
const payMethodsEl = document.querySelector("#pay-methods");
const receiptInput = document.querySelector("#payer-receipt");
const receiptName = document.querySelector("#receipt-name");
const clearCartBtn = document.querySelector("#clear-cart");
const discountInput = document.querySelector("#shop-discount-code");
const discountApply = document.querySelector("#shop-discount-apply");
const discountStatus = document.querySelector("#shop-discount-status");
const cartSavingsEl = document.querySelector("#cart-savings");
const cartDrawer = document.querySelector("#cart-drawer");
const cartOpen = document.querySelector("#cart-open");
const cartClose = document.querySelector("#cart-close");
const cartBackdrop = document.querySelector("#cart-backdrop");

const BRAND_TONES = {
  netflix: "#e50914",
  disney: "#113ccf",
  hbo: "#b1092d",
  prime: "#00a8e1",
  paramount: "#0064ff",
  appletv: "#1d1d1f",
  starplus: "#eb168e",
  vix: "#ff6a00",
  crunchyroll: "#f47521",
  youtube: "#ff0033",
  spotify: "#1db954",
  applemusic: "#fc3c44",
  deezer: "#a238ff",
  tidal: "#000000",
  amazonmusic: "#25d1da",
  canva: "#00c4cc",
  chatgpt: "#10a37f",
  xbox: "#107c10",
  playstation: "#003791",
  nordvpn: "#4687ff",
  cali: "#1f6b4a",
  open: "#c45c26",
};

let catalog = [];
let whatsappPhone = "";
let paymentMethods = [];
let messageTemplate = "Hola, quiero comprar:\n{items}\nTotal: {total}";
let cart = loadCart();
let searchQuery = "";
let categoryFilter = "";
let appliedDiscount = null;

function loadCart() {
  try {
    const raw = localStorage.getItem(CART_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== "object") return {};
    const cart = {};
    for (const [key, qty] of Object.entries(parsed)) {
      const next = Math.max(0, Math.min(1, Number(qty) || 0));
      if (next) cart[key] = next;
    }
    return cart;
  } catch {
    return {};
  }
}

function saveCart() {
  localStorage.setItem(CART_KEY, JSON.stringify(cart));
}

function formatCop(amount) {
  return `$${Number(amount || 0).toLocaleString("es-CO")}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function productByKey(key) {
  return catalog.find((item) => item.key === key);
}

function cartEntries() {
  return Object.entries(cart)
    .map(([key, qty]) => {
      const product = productByKey(key);
      if (!product || qty < 1) return null;
      return { product, qty: Number(qty) };
    })
    .filter(Boolean);
}

function cartCount() {
  return cartEntries().reduce((sum, row) => sum + row.qty, 0);
}

function cartSubtotal() {
  return cartEntries().reduce((sum, row) => sum + row.product.price_cop * row.qty, 0);
}

function cartTotals() {
  const subtotal = cartSubtotal();
  if (!appliedDiscount) return { subtotal, savings: 0, total: subtotal };
  const savings = Math.max(0, Math.min(subtotal, Number(appliedDiscount.savings || 0)));
  return { subtotal, savings, total: subtotal - savings };
}

function brandTone(product) {
  return BRAND_TONES[product.key] || "#2c3fad";
}

function brandInitials(label) {
  const words = String(label || "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0][0]}${words[1][0]}`.toUpperCase();
}

function setQty(key, qty) {
  const next = Math.max(0, Math.min(1, Number(qty) || 0));
  if (next <= 0) delete cart[key];
  else cart[key] = next;
  saveCart();
  refreshDiscountSavings().then(renderCart);
  renderCatalog();
}

function addToCart(key) {
  setQty(key, (cart[key] || 0) + 1);
  openCart();
}

function renderPayMethods() {
  if (!payMethodsEl) return;
  if (!paymentMethods.length) {
    payMethodsEl.innerHTML = `<p class="pay-empty">Todavía no hay formas de pago activas. Vuelve más tarde.</p>`;
    return;
  }
  payMethodsEl.innerHTML = paymentMethods.map((method, index) => `
    <label class="pay-method${index === 0 ? " is-selected" : ""}">
      <span class="pay-method-pick">
        <input type="radio" name="payment-method" value="${escapeHtml(method.label)}" ${index === 0 ? "checked" : ""}>
        Pagué con ${escapeHtml(method.label)}
      </span>
      <div class="pay-row">
        <div>
          <p>${escapeHtml(method.detail_label || "Dato")}</p>
          <strong>${escapeHtml(method.key_value)}</strong>
        </div>
        <button class="secondary compact copy-pay-key" type="button" data-copy="${escapeHtml(method.key_value)}">Copiar</button>
      </div>
      ${method.instructions ? `<p>${escapeHtml(method.instructions)}</p>` : ""}
    </label>
  `).join("");
}

function selectedPaymentMethod() {
  return document.querySelector('input[name="payment-method"]:checked')?.value || "";
}

function openCheckout() {
  if (!cartEntries().length) return;
  if (payAmount) payAmount.textContent = formatCop(cartTotals().total);
  renderPayMethods();
  if (checkoutStatus) checkoutStatus.textContent = "";
  if (checkoutModal) {
    checkoutModal.hidden = false;
    document.body.classList.add("cart-open");
  }
}

function closeCheckout() {
  if (checkoutModal) checkoutModal.hidden = true;
  if (!cartDrawer || cartDrawer.hidden) document.body.classList.remove("cart-open");
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    /* El navegador puede bloquear el portapapeles. */
  }
}

function filteredProducts() {
  const query = searchQuery.trim().toLowerCase();
  return catalog.filter((product) => {
    if (categoryFilter && product.category !== categoryFilter) return false;
    if (!query) return true;
    const extras = (product.items || []).map((i) => i.label).join(" ");
    const haystack = `${product.label} ${product.blurb} ${product.category} ${extras}`.toLowerCase();
    return haystack.includes(query);
  });
}

function fillCategoryOptions() {
  if (!shopCategory) return;
  const current = shopCategory.value;
  const categories = [...new Set(catalog.map((p) => p.category))].sort((a, b) => a.localeCompare(b, "es"));
  shopCategory.innerHTML = `<option value="">Todas</option>${categories
    .map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)
    .join("")}`;
  if (categories.includes(current)) shopCategory.value = current;
}

function renderCatalog() {
  if (!shopCatalog) return;
  const products = filteredProducts();
  if (!products.length) {
    shopCatalog.innerHTML = "<p class=\"muted\">No hay productos con ese filtro.</p>";
    return;
  }
  shopCatalog.innerHTML = products.map((product) => {
    const qty = cart[product.key] || 0;
    const inStock = product.kind === "combo" || (product.stock_available || 0) > 0 || !("stock_available" in product);
    const stockLabel = product.kind === "combo"
      ? "combo"
      : (product.stock_available || 0) > 0
        ? "disponible"
        : "consultar";
    const title = product.blurb
      ? `CUENTA ${product.label}`.toUpperCase()
      : product.label.toUpperCase();
    return `
      <article class="store-card" data-key="${escapeHtml(product.key)}">
        <div class="store-card-logo" style="--brand:${brandTone(product)}">
          <span>${escapeHtml(brandInitials(product.label))}</span>
        </div>
        <h3 class="store-card-title">${escapeHtml(title)}</h3>
        ${product.kind === "combo" && product.items?.length
          ? `<p class="store-card-meta">${escapeHtml(product.items.map((i) => i.label).join(" · "))}</p>`
          : product.blurb
            ? `<p class="store-card-meta">${escapeHtml(product.blurb)}</p>`
            : ""}
        <p class="store-card-price">${formatCop(product.price_cop)}</p>
        <div class="store-card-foot">
          <span class="store-card-stock ${inStock ? "ok" : ""}">${stockLabel}</span>
          <button type="button" class="store-card-add add-to-cart" data-key="${escapeHtml(product.key)}">
            ${qty > 0 ? `Añadir (${qty})` : "Añadir"}
          </button>
        </div>
      </article>`;
  }).join("");
}

function renderCart() {
  const entries = cartEntries();
  const count = cartCount();
  const { savings, total } = cartTotals();
  if (cartBadge) {
    cartBadge.hidden = count === 0;
    cartBadge.textContent = String(count);
  }
  if (cartEmpty) cartEmpty.hidden = entries.length > 0;
  if (cartItemsEl) {
    cartItemsEl.innerHTML = entries.map(({ product, qty }) => `
      <div class="cart-line" data-key="${escapeHtml(product.key)}">
        <div>
          <strong>${escapeHtml(product.label)}${product.kind === "combo" ? " (combo)" : ""}</strong>
          <small>${formatCop(product.price_cop)} c/u</small>
        </div>
        <div class="cart-qty">
          <button type="button" class="secondary compact qty-minus" data-key="${escapeHtml(product.key)}" aria-label="Menos">−</button>
          <span>${qty}</span>
          <button type="button" class="secondary compact qty-plus" data-key="${escapeHtml(product.key)}" aria-label="Más">+</button>
          <button type="button" class="danger compact qty-remove" data-key="${escapeHtml(product.key)}" aria-label="Quitar">×</button>
        </div>
        <strong class="cart-line-total">${formatCop(product.price_cop * qty)}</strong>
      </div>
    `).join("");
  }
  if (cartSavingsEl) {
    cartSavingsEl.hidden = savings <= 0;
    cartSavingsEl.textContent = savings > 0 ? `Descuento: -${formatCop(savings)}` : "";
  }
  if (cartTotalEl) cartTotalEl.textContent = formatCop(total);
  if (checkoutOpen) checkoutOpen.disabled = entries.length === 0;
}

function openCart() {
  if (!cartDrawer) return;
  cartDrawer.hidden = false;
  document.body.classList.add("cart-open");
}

function closeCart() {
  if (!cartDrawer) return;
  cartDrawer.hidden = true;
  document.body.classList.remove("cart-open");
}

async function refreshDiscountSavings() {
  if (!appliedDiscount?.code) return;
  const subtotal = cartSubtotal();
  if (subtotal <= 0) {
    appliedDiscount = null;
    if (discountStatus) discountStatus.textContent = "";
    return;
  }
  try {
    const result = await apiRequest("/api/shop/discount", {
      method: "POST",
      body: JSON.stringify({ code: appliedDiscount.code, subtotal }),
    });
    appliedDiscount = result;
    if (discountStatus) {
      discountStatus.textContent = `Cupón ${result.code} aplicado (−${formatCop(result.savings)})`;
      discountStatus.className = "form-hint ok-hint";
    }
  } catch {
    appliedDiscount = null;
    if (discountStatus) {
      discountStatus.textContent = "El cupón ya no aplica.";
      discountStatus.className = "form-hint";
    }
  }
}

async function applyDiscountCode() {
  const code = (discountInput?.value || "").trim();
  if (!code) {
    appliedDiscount = null;
    if (discountStatus) discountStatus.textContent = "";
    renderCart();
    return;
  }
  const subtotal = cartSubtotal();
  if (subtotal <= 0) {
    if (discountStatus) {
      discountStatus.textContent = "Añade productos antes de aplicar el cupón.";
      discountStatus.className = "form-hint";
    }
    return;
  }
  try {
    const result = await apiRequest("/api/shop/discount", {
      method: "POST",
      body: JSON.stringify({ code, subtotal }),
    });
    appliedDiscount = result;
    if (discountStatus) {
      discountStatus.textContent = `Cupón ${result.code} aplicado (−${formatCop(result.savings)})`;
      discountStatus.className = "form-hint ok-hint";
    }
    renderCart();
  } catch (error) {
    appliedDiscount = null;
    if (discountStatus) {
      discountStatus.textContent = error.message || "Cupón no válido.";
      discountStatus.className = "form-hint";
    }
    renderCart();
  }
}

shopSearch?.addEventListener("input", () => {
  searchQuery = shopSearch.value || "";
  renderCatalog();
});

shopCategory?.addEventListener("change", () => {
  categoryFilter = shopCategory.value || "";
  renderCatalog();
});

shopCatalog?.addEventListener("click", (event) => {
  const button = event.target.closest(".add-to-cart");
  if (!button) return;
  addToCart(button.dataset.key);
});

cartItemsEl?.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const key = button.dataset.key;
  if (button.classList.contains("qty-plus")) setQty(key, (cart[key] || 0) + 1);
  if (button.classList.contains("qty-minus")) setQty(key, (cart[key] || 0) - 1);
  if (button.classList.contains("qty-remove")) setQty(key, 0);
});

clearCartBtn?.addEventListener("click", () => {
  cart = {};
  appliedDiscount = null;
  if (discountInput) discountInput.value = "";
  if (discountStatus) discountStatus.textContent = "";
  saveCart();
  renderCart();
  renderCatalog();
});

discountApply?.addEventListener("click", () => applyDiscountCode());
discountInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    applyDiscountCode();
  }
});

cartOpen?.addEventListener("click", openCart);
cartClose?.addEventListener("click", closeCart);
cartBackdrop?.addEventListener("click", closeCart);

checkoutOpen?.addEventListener("click", openCheckout);
checkoutClose?.addEventListener("click", closeCheckout);
checkoutBackdrop?.addEventListener("click", closeCheckout);
document.querySelector("#copy-amount")?.addEventListener("click", () => {
  copyText(String(cartTotals().total));
});
payMethodsEl?.addEventListener("click", (event) => {
  const button = event.target.closest(".copy-pay-key");
  if (!button) return;
  event.preventDefault();
  copyText(button.dataset.copy || "");
});
payMethodsEl?.addEventListener("change", (event) => {
  if (event.target.name !== "payment-method") return;
  payMethodsEl.querySelectorAll(".pay-method").forEach((card) => {
    card.classList.toggle("is-selected", card.contains(event.target));
  });
});
receiptInput?.addEventListener("change", () => {
  const file = receiptInput.files?.[0];
  if (receiptName) receiptName.textContent = file ? file.name : "JPG, PNG o WEBP";
});
checkoutForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const entries = cartEntries();
  if (!entries.length) return;
  const file = receiptInput?.files?.[0];
  if (!file) {
    if (checkoutStatus) checkoutStatus.textContent = "Sube la imagen del comprobante.";
    return;
  }
  if (paymentMethods.length && !selectedPaymentMethod()) {
    if (checkoutStatus) checkoutStatus.textContent = "Elige la forma de pago que usaste.";
    return;
  }
  const submit = document.querySelector("#checkout-submit");
  if (submit) submit.disabled = true;
  if (checkoutStatus) checkoutStatus.textContent = "Enviando comprobante...";
  const body = new FormData();
  body.set("payer_name", document.querySelector("#payer-name").value.trim());
  body.set("whatsapp", document.querySelector("#payer-whatsapp").value.trim());
  body.set("payment_method", selectedPaymentMethod());
  body.set("discount_code", appliedDiscount?.code || "");
  body.set("items", JSON.stringify(entries.map(({ product, qty }) => ({
    key: product.key,
    label: product.label,
    kind: product.kind || "product",
    qty,
  }))));
  body.set("receipt", file);
  try {
    const response = await fetch("/api/shop/orders", { method: "POST", body, credentials: "same-origin" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "No se pudo crear el pedido.");
    window.open(payload.whatsapp_url, "_blank", "noopener");
    cart = {};
    appliedDiscount = null;
    if (discountInput) discountInput.value = "";
    saveCart();
    renderCart();
    renderCatalog();
    closeCheckout();
    closeCart();
    if (checkoutStatus) checkoutStatus.textContent = "";
  } catch (error) {
    if (checkoutStatus) checkoutStatus.textContent = error.message;
  } finally {
    if (submit) submit.disabled = false;
  }
});

apiRequest("/api/shop/catalog")
  .then((payload) => {
    const products = payload.products || [];
    const combos = payload.combos || [];
    catalog = [...products, ...combos];
    whatsappPhone = payload.whatsapp?.phone || "";
    paymentMethods = payload.payment_methods || [];
    messageTemplate = payload.whatsapp?.message_template || messageTemplate;
    fillCategoryOptions();
    renderCatalog();
    renderCart();
  })
  .catch(() => {
    if (shopCatalog) {
      shopCatalog.innerHTML = "<p class=\"muted\">No se pudo cargar el catálogo.</p>";
    }
  });
