import html
import imaplib
import json
import logging
import sqlite3
from urllib.parse import quote

from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import get_settings
from app.database import (
    assign_account,
    build_admin_summary,
    configure_encryption,
    create_account,
    create_client,
    create_main_account,
    delete_account,
    delete_client,
    delete_main_account,
    digits_only,
    find_client_access,
    init_database,
    list_accounts,
    list_assignments,
    list_audit_events,
    list_clients,
    list_main_accounts,
    migrate_plaintext_secrets,
    record_audit,
    record_lookup,
    unassign_account,
    update_account,
    update_account_expiration,
    update_client,
    update_main_account,
    update_main_account_password,
)
from app.imap_client import (
    credentials_from_main_account,
    credentials_from_settings,
    find_recent_code,
    find_recent_household_link,
)
from app.netflix_link import resolve_household_code
from app.orders import (
    admin_whatsapp_text,
    approve_order,
    create_order,
    credentials_message,
    get_order,
    load_approved_accounts,
    receipt_file,
    reject_order,
    save_receipt,
)
from app.platforms import get_platform, list_platforms
from app.security import (
    RateLimiter,
    SecurityHeadersMiddleware,
    clear_auth_cookies,
    client_ip,
    create_admin_session,
    derive_fernet,
    read_session_cookie,
    require_csrf,
    secure_equals,
    set_auth_cookies,
    verify_admin_session,
)
from app.shop import format_cop
from app.shop_store import (
    apply_discount_amount,
    create_shop_combo,
    create_shop_discount,
    create_shop_product,
    create_shop_stock,
    delete_shop_combo,
    delete_shop_discount,
    delete_shop_product,
    delete_shop_stock,
    list_shop_combos,
    list_shop_products_public,
    resolve_shop_discount,
    seed_shop_products,
    shop_admin_bundle,
    update_shop_combo,
    update_shop_discount,
    update_shop_product,
    update_shop_stock,
)

logger = logging.getLogger("centralcode.security")
settings = get_settings()
fernet = derive_fernet(settings.encryption_secret)
limiter = RateLimiter()

_openapi_url = "/openapi.json" if settings.openapi_enabled and not settings.is_production else None
_docs_url = "/docs" if settings.openapi_enabled and not settings.is_production else None

app = FastAPI(
    title=settings.app_name,
    docs_url=_docs_url,
    redoc_url=None,
    openapi_url=_openapi_url,
)
app.add_middleware(SecurityHeadersMiddleware, app_env=settings.app_env)
_hosts = [host.strip() for host in settings.trusted_hosts.split(",") if host.strip()]
if settings.is_production and _hosts and _hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_hosts)
app.mount("/static", StaticFiles(directory="static", html=False, check_dir=True), name="static")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "Solicitud inválida."})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Error no controlado en %s", request.url.path)
    detail = "Error interno del servidor."
    return JSONResponse(status_code=500, content={"detail": detail})


class LookupRequest(BaseModel):
    platform: str = Field(min_length=1, max_length=48)
    identifier: str = Field(min_length=7, max_length=20)
    code_type: Literal["login", "household"] = "login"


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=1, max_length=160)


class AccountRequest(BaseModel):
    platform: str
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(default="", max_length=160)
    password: str = Field(default="", max_length=160)
    expires_at: str = Field(min_length=8, max_length=40)
    main_account_id: int | None = None
    subdomain: str = Field(default="", max_length=80)


class AccountExpirationRequest(BaseModel):
    expires_at: str = Field(min_length=8, max_length=40)


class MainAccountRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(default="", max_length=160)
    domain: str = Field(min_length=3, max_length=160)
    imap_host: str = Field(min_length=1, max_length=160)
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_folder: str = Field(default="INBOX", min_length=1, max_length=80)


class MainAccountPasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=160)


class ClientRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=5, max_length=30)


class AssignmentRequest(BaseModel):
    client_id: int
    account_id: int
    assigned_at: str | None = None


class ShopProductRequest(BaseModel):
    key: str = Field(default="", max_length=48)
    label: str = Field(min_length=1, max_length=80)
    price_cop: int = Field(ge=0, le=10_000_000)
    blurb: str = Field(default="", max_length=160)
    category: str = Field(default="General", max_length=40)
    active: bool = True
    otp_senders: str = Field(default="", max_length=240)
    otp_subjects: str = Field(default="", max_length=240)


class ShopComboItemRequest(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=20)


class ShopComboRequest(BaseModel):
    key: str = Field(default="", max_length=48)
    label: str = Field(min_length=1, max_length=80)
    price_cop: int = Field(ge=0, le=10_000_000)
    blurb: str = Field(default="", max_length=160)
    active: bool = True
    items: list[ShopComboItemRequest] = Field(min_length=1)


class ShopDiscountRequest(BaseModel):
    code: str = Field(default="", max_length=40)
    label: str = Field(min_length=1, max_length=80)
    discount_type: str = Field(pattern="^(percent|fixed)$")
    value: float = Field(gt=0, le=10_000_000)
    active: bool = True
    expires_at: str | None = None


class ShopStockRequest(BaseModel):
    product_id: int
    login: str = Field(min_length=1, max_length=160)
    password: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=240)
    status: str = Field(default="available", pattern="^(available|sold|reserved)$")


class ShopDiscountCheckRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    subtotal: int = Field(default=0, ge=0, le=50_000_000)


@app.on_event("startup")
def startup() -> None:
    if settings.is_production and settings.uses_insecure_defaults:
        raise RuntimeError(
            "Producción con ADMIN_PASSWORD o SESSION_SECRET por defecto. "
            "Cámbialos en .env antes de arrancar."
        )
    if settings.is_production and settings.trusted_hosts.strip() in {"", "*"}:
        logger.warning("TRUSTED_HOSTS=* en producción. Define tu dominio real.")
    configure_encryption(fernet)
    init_database(settings.database_path)
    seed_shop_products(settings.database_path)
    migrated = migrate_plaintext_secrets(settings.database_path)
    if migrated:
        logger.warning("Se cifraron %s credenciales que estaban en texto plano.", migrated)


def require_admin(request: Request) -> dict:
    ip = client_ip(request)
    limiter.hit(
        f"admin-api:{ip}",
        settings.admin_api_rate_limit,
        settings.admin_api_window_seconds,
    )
    session_value = read_session_cookie(request, prefer_host=settings.is_production)
    payload = verify_admin_session(settings.session_secret, session_value)
    if payload is None:
        raise HTTPException(status_code=401, detail="Debes iniciar sesión como administrador.")
    require_csrf(request, payload, prefer_host=settings.is_production)
    return payload


def _db_call(action, *, status_code: int = 400):
    try:
        return action()
    except ValueError as error:
        raise HTTPException(status_code=status_code, detail=str(error)) from error


def _require_platform(key: str):
    platform = get_platform(settings.database_path, key)
    if platform is None:
        raise HTTPException(status_code=400, detail="La plataforma no es válida. Crea el producto en Tienda primero.")
    return platform


def build_whatsapp_renewal(platform_label: str, identifier: str) -> dict[str, str]:
    number = digits_only(settings.whatsapp_bot_number)
    message = settings.whatsapp_renewal_message.format(
        platform=platform_label,
        identifier=identifier.strip(),
    )
    return {
        "phone": number,
        "message": message,
        "url": f"https://wa.me/{number}?text={quote(message)}",
    }


def _audit(request: Request, action: str, target: str | None = None, detail: str | None = None) -> None:
    record_audit(
        settings.database_path,
        settings.admin_email,
        action,
        target=target,
        detail=detail,
        ip_address=client_ip(request),
    )


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/tienda", include_in_schema=False)
def shop_page() -> FileResponse:
    return FileResponse("static/shop.html")


@app.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    return FileResponse("static/admin.html")


@app.post("/api/admin/login", include_in_schema=False)
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, bool]:
    ip = client_ip(request)
    login_key = f"admin-login:{ip}"
    limiter.assert_not_locked(login_key)
    limiter.hit(login_key, settings.admin_login_rate_limit, settings.admin_login_window_seconds)

    email_ok = secure_equals(payload.email.casefold(), settings.admin_email.casefold())
    password_ok = secure_equals(payload.password, settings.admin_password)
    if not email_ok or not password_ok:
        limiter.register_failure(
            login_key,
            settings.admin_login_rate_limit,
            settings.admin_login_window_seconds,
            settings.admin_lockout_seconds,
        )
        record_audit(
            settings.database_path,
            payload.email.strip()[:80] or "unknown",
            "login_failed",
            ip_address=ip,
        )
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")

    limiter.clear_failures(login_key)
    session_value, csrf_token = create_admin_session(
        settings.session_secret,
        settings.session_lifetime_seconds,
    )
    set_auth_cookies(
        response,
        session_value,
        csrf_token,
        secure=settings.is_production,
        max_age=settings.session_lifetime_seconds,
    )
    record_audit(settings.database_path, settings.admin_email, "login_success", ip_address=ip)
    return {"authenticated": True}


@app.post("/api/admin/logout", include_in_schema=False)
def logout(request: Request, response: Response) -> dict[str, bool]:
    session_value = read_session_cookie(request, prefer_host=settings.is_production)
    payload = verify_admin_session(settings.session_secret, session_value)
    if payload is not None:
        require_csrf(request, payload, prefer_host=settings.is_production)
        record_audit(
            settings.database_path,
            settings.admin_email,
            "logout",
            ip_address=client_ip(request),
        )
    clear_auth_cookies(response)
    return {"authenticated": False}


@app.get("/api/admin/data")
def admin_data(_: dict = Depends(require_admin)) -> dict:
    mains = list_main_accounts(settings.database_path)
    accounts = list_accounts(settings.database_path)
    clients = list_clients(settings.database_path)
    assignments = list_assignments(settings.database_path)
    shop = shop_admin_bundle(settings.database_path)
    return {
        "summary": build_admin_summary(mains, accounts, clients, assignments),
        "main_accounts": mains,
        "accounts": accounts,
        "clients": clients,
        "assignments": assignments,
        "shop": shop,
        "platforms": list_platforms(settings.database_path, active_only=True),
        "audit": list_audit_events(settings.database_path, limit=40),
    }


@app.post("/api/admin/main-accounts")
def add_main_account(
    payload: MainAccountRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, int]:
    if not payload.password.strip():
        raise HTTPException(status_code=400, detail="La contraseña IMAP es obligatoria.")
    main_account_id = _db_call(
        lambda: create_main_account(
            settings.database_path,
            payload.name.strip(),
            payload.email.strip(),
            payload.password,
            payload.domain.strip(),
            payload.imap_host.strip(),
            payload.imap_port,
            payload.imap_folder.strip() or "INBOX",
        )
    )
    _audit(request, "main_account_create", target=str(main_account_id), detail=payload.email.strip())
    return {"id": main_account_id}


@app.put("/api/admin/main-accounts/{main_account_id}")
def edit_main_account(
    main_account_id: int,
    payload: MainAccountRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(
        lambda: update_main_account(
            settings.database_path,
            main_account_id,
            payload.name.strip(),
            payload.email.strip(),
            payload.domain.strip(),
            payload.imap_host.strip(),
            payload.imap_port,
            payload.imap_folder.strip() or "INBOX",
            payload.password or None,
        )
    )
    _audit(request, "main_account_update", target=str(main_account_id))
    return {"updated": True}


@app.delete("/api/admin/main-accounts/{main_account_id}")
def remove_main_account(
    main_account_id: int,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(lambda: delete_main_account(settings.database_path, main_account_id), status_code=404)
    _audit(request, "main_account_delete", target=str(main_account_id))
    return {"deleted": True}


@app.patch("/api/admin/main-accounts/{main_account_id}/password")
def renew_main_account_password(
    main_account_id: int,
    payload: MainAccountPasswordRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(lambda: update_main_account_password(settings.database_path, main_account_id, payload.password))
    _audit(request, "main_account_password_update", target=str(main_account_id))
    return {"updated": True}


@app.post("/api/admin/accounts")
def add_account(
    payload: AccountRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, int]:
    _require_platform(payload.platform)
    if payload.main_account_id is None and not payload.email.strip():
        raise HTTPException(status_code=400, detail="Indica el correo alias de la cuenta.")
    if not payload.password.strip():
        raise HTTPException(status_code=400, detail="La contraseña de la cuenta es obligatoria.")
    account_id = _db_call(
        lambda: create_account(
            settings.database_path,
            payload.platform,
            payload.name.strip(),
            payload.email.strip(),
            payload.password,
            payload.expires_at,
            payload.main_account_id,
            payload.subdomain.strip() or None,
        )
    )
    _audit(request, "account_create", target=str(account_id), detail=payload.email.strip())
    return {"id": account_id}


@app.put("/api/admin/accounts/{account_id}")
def edit_account(
    account_id: int,
    payload: AccountRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _require_platform(payload.platform)
    _db_call(
        lambda: update_account(
            settings.database_path,
            account_id,
            payload.platform,
            payload.name.strip(),
            payload.email.strip(),
            payload.expires_at,
            payload.main_account_id,
            payload.subdomain.strip() or None,
            payload.password or None,
        )
    )
    _audit(request, "account_update", target=str(account_id))
    return {"updated": True}


@app.delete("/api/admin/accounts/{account_id}")
def remove_account(
    account_id: int,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(lambda: delete_account(settings.database_path, account_id), status_code=404)
    _audit(request, "account_delete", target=str(account_id))
    return {"deleted": True}


@app.patch("/api/admin/accounts/{account_id}/expiration")
def renew_account(
    account_id: int,
    payload: AccountExpirationRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(lambda: update_account_expiration(settings.database_path, account_id, payload.expires_at))
    _audit(request, "account_renew", target=str(account_id))
    return {"updated": True}


@app.post("/api/admin/clients")
def add_client(
    payload: ClientRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, int]:
    try:
        client_id = create_client(settings.database_path, payload.name.strip(), payload.phone.strip())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Ese celular ya está registrado.") from error
    _audit(request, "client_create", target=str(client_id))
    return {"id": client_id}


@app.put("/api/admin/clients/{client_id}")
def edit_client(
    client_id: int,
    payload: ClientRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    try:
        update_client(settings.database_path, client_id, payload.name.strip(), payload.phone.strip())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Ese celular ya está registrado.") from error
    _audit(request, "client_update", target=str(client_id))
    return {"updated": True}


@app.delete("/api/admin/clients/{client_id}")
def remove_client(
    client_id: int,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(lambda: delete_client(settings.database_path, client_id), status_code=404)
    _audit(request, "client_delete", target=str(client_id))
    return {"deleted": True}


@app.post("/api/admin/assignments")
def add_assignment(
    payload: AssignmentRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(
        lambda: assign_account(
            settings.database_path,
            payload.client_id,
            payload.account_id,
            payload.assigned_at,
        ),
        status_code=409,
    )
    _audit(request, "assignment_create", target=f"{payload.client_id}:{payload.account_id}")
    return {"assigned": True}


@app.delete("/api/admin/assignments/{client_id}/{account_id}")
def remove_assignment(
    client_id: int,
    account_id: int,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(lambda: unassign_account(settings.database_path, client_id, account_id), status_code=404)
    _audit(request, "assignment_delete", target=f"{client_id}:{account_id}")
    return {"unassigned": True}


@app.get("/api/platforms")
def platforms() -> list[dict[str, str]]:
    return list_platforms(settings.database_path, active_only=True)


@app.get("/api/shop/catalog")
def shop_catalog() -> dict:
    number = digits_only(settings.whatsapp_bot_number)
    products = list_shop_products_public(settings.database_path)
    combos = [
        {
            "key": combo["key"],
            "label": combo["label"],
            "price_cop": combo["price_cop"],
            "blurb": combo["blurb"],
            "category": "Combos",
            "kind": "combo",
            "items": [
                {"key": item["key"], "label": item["label"], "quantity": item["quantity"]}
                for item in combo["items"]
            ],
        }
        for combo in list_shop_combos(settings.database_path, active_only=True)
    ]
    return {
        "currency": "COP",
        "products": products,
        "combos": combos,
        "whatsapp": {
            "phone": number,
            "message_template": settings.whatsapp_shop_message,
        },
        "breb_key": digits_only(settings.breb_key),
    }


@app.post("/api/shop/discount")
def shop_discount_check(payload: ShopDiscountCheckRequest) -> dict:
    discount = resolve_shop_discount(settings.database_path, payload.code)
    if discount is None:
        raise HTTPException(status_code=404, detail="Cupón no válido o vencido.")
    total, savings = apply_discount_amount(payload.subtotal, discount)
    return {
        "valid": True,
        "code": discount["code"],
        "label": discount["label"],
        "discount_type": discount["discount_type"],
        "value": discount["value"],
        "subtotal": payload.subtotal,
        "savings": savings,
        "total": total,
    }


def _public_base(request: Request) -> str:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    return f"{proto}://{host}".rstrip("/")


def _wa_number(value: str) -> str:
    digits = digits_only(value)
    if len(digits) == 10 and digits.startswith("3"):
        return f"57{digits}"
    return digits


@app.post("/api/shop/orders")
async def shop_create_order(
    request: Request,
    payer_name: str = Form(min_length=3, max_length=80),
    whatsapp: str = Form(min_length=7, max_length=20),
    items: str = Form(min_length=2, max_length=8000),
    discount_code: str = Form(default="", max_length=40),
    receipt: UploadFile = File(...),
) -> dict:
    limiter.hit(f"order:{client_ip(request)}", 8, 300)
    try:
        parsed_items = json.loads(items)
        if not isinstance(parsed_items, list) or not parsed_items:
            raise ValueError("El carrito está vacío.")
        content = await receipt.read()
        receipt_path = save_receipt(content, receipt.content_type or "")
        order = create_order(
            settings.database_path,
            payer_name=payer_name,
            whatsapp=whatsapp,
            items=parsed_items,
            discount_code=discount_code,
            receipt_path=receipt_path,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="El carrito no es válido.") from error
    stored = get_order(settings.database_path, order["token"])
    base = _public_base(request)
    review_url = f"{base}/pedido/{order['token']}"
    text = admin_whatsapp_text(stored, review_url, f"{review_url}/comprobante")
    phone = _wa_number(settings.whatsapp_bot_number)
    return {
        "order_id": order["id"],
        "whatsapp_url": f"https://wa.me/{phone}?text={quote(text)}",
    }


@app.get("/pedido/{token}/comprobante")
def shop_order_receipt(token: str) -> FileResponse:
    found = receipt_file(settings.database_path, token)
    if found is None:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado.")
    path, media = found
    return FileResponse(path, media_type=media)


@app.get("/pedido/{token}", response_class=HTMLResponse)
def shop_order_review(token: str) -> HTMLResponse:
    order = get_order(settings.database_path, token)
    if order is None:
        raise HTTPException(status_code=404, detail="Pedido no encontrado.")
    return HTMLResponse(_order_review_html(order))


@app.post("/pedido/{token}/autorizar", response_class=HTMLResponse)
def shop_order_approve(token: str) -> HTMLResponse:
    try:
        result = approve_order(settings.database_path, token)
    except ValueError as error:
        order = get_order(settings.database_path, token)
        if order is None:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return HTMLResponse(_order_review_html(order, notice=str(error)))
    message = credentials_message(result["order"]["payer_name"], result["accounts"])
    customer = _wa_number(result["order"]["whatsapp"])
    url = f"https://wa.me/{customer}?text={quote(message)}"
    order = get_order(settings.database_path, token)
    return HTMLResponse(_order_review_html(order, customer_url=url, auto_open=True))


@app.post("/pedido/{token}/rechazar", response_class=HTMLResponse)
def shop_order_reject(token: str) -> HTMLResponse:
    try:
        reject_order(settings.database_path, token)
    except ValueError as error:
        order = get_order(settings.database_path, token)
        if order is None:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return HTMLResponse(_order_review_html(order, notice=str(error)))
    order = get_order(settings.database_path, token)
    return HTMLResponse(_order_review_html(order, notice="Pedido rechazado. No se entregaron cuentas."))


def _order_review_html(order: dict, *, notice: str = "", customer_url: str = "", auto_open: bool = False) -> str:
    lines = "".join(
        f"<li>{html.escape(str(item.get('label') or item.get('key')))} × {int(item.get('qty') or 0)}</li>"
        for item in order["items"]
    )
    status = order["status"]
    actions = ""
    if status == "pending":
        actions = f"""
        <p class="ask">¿Autorizas este pago?</p>
        <form method="post" action="/pedido/{html.escape(order['token'])}/autorizar">
          <button class="yes" type="submit">Autorizar</button>
        </form>
        <form method="post" action="/pedido/{html.escape(order['token'])}/rechazar">
          <button class="no" type="submit">Rechazar</button>
        </form>
        """
    elif status == "approved" and not customer_url:
        accounts = load_approved_accounts(settings.database_path, order)
        if accounts:
            message = credentials_message(order["payer_name"], accounts)
            customer_url = f"https://wa.me/{_wa_number(order['whatsapp'])}?text={quote(message)}"
    send = ""
    if customer_url:
        send = (
            f'<a class="yes link" href="{html.escape(customer_url)}">Enviar cuentas por WhatsApp</a>'
            "<p class=\"hint\">Se abre el chat del cliente con correo y contraseña listos. Pulsa enviar.</p>"
        )
    note = f"<p class=\"notice\">{html.escape(notice)}</p>" if notice else ""
    opener = (
        f'<meta http-equiv="refresh" content="0;url={html.escape(customer_url)}">'
        if auto_open and customer_url
        else ""
    )
    return f"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{opener}
<title>Pedido #{int(order['id'])}</title>
<style>
  body {{ font-family: "Segoe UI", sans-serif; background:#f6f3ec; color:#1c1915; margin:0; padding:1.2rem; }}
  main {{ max-width:28rem; margin:0 auto; background:#fffdf9; border:1px solid #e3dacd; border-radius:1.1rem; padding:1.2rem; }}
  img {{ width:100%; border-radius:.8rem; margin-top:.6rem; }}
  .yes, .no {{ width:100%; min-height:3rem; border:0; border-radius:.8rem; font-weight:800; margin-top:.6rem; cursor:pointer; }}
  .yes {{ background:#163832; color:white; }}
  .no {{ background:#fff; color:#9b1c1c; border:1px solid #e7b4b4; }}
  a.link {{ display:block; text-align:center; text-decoration:none; padding:.85rem; }}
  .notice {{ background:#fff6e8; border-radius:.7rem; padding:.7rem; }}
  .ask {{ font-weight:800; }}
</style></head><body><main>
  <p>Pedido #{int(order['id'])} · {html.escape(status)}</p>
  <h1>{html.escape(order['payer_name'])}</h1>
  <p>WhatsApp {html.escape(order['whatsapp'])}<br>Total {html.escape(format_cop(int(order['total'])))}</p>
  <ul>{lines}</ul>
  <img src="/pedido/{html.escape(order['token'])}/comprobante" alt="Comprobante de pago">
  {note}{actions}{send}
</main></body></html>"""


@app.post("/api/admin/shop/products")
def add_shop_product(
    payload: ShopProductRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, int]:
    product_id = _db_call(
        lambda: create_shop_product(
            settings.database_path,
            key=payload.key,
            label=payload.label,
            price_cop=payload.price_cop,
            blurb=payload.blurb,
            category=payload.category,
            active=payload.active,
            otp_senders=payload.otp_senders,
            otp_subjects=payload.otp_subjects,
        )
    )
    _audit(request, "shop_product_create", target=str(product_id), detail=payload.label)
    return {"id": product_id}


@app.put("/api/admin/shop/products/{product_id}")
def edit_shop_product(
    product_id: int,
    payload: ShopProductRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(
        lambda: update_shop_product(
            settings.database_path,
            product_id,
            label=payload.label,
            price_cop=payload.price_cop,
            blurb=payload.blurb,
            category=payload.category,
            active=payload.active,
            otp_senders=payload.otp_senders,
            otp_subjects=payload.otp_subjects,
        ),
        status_code=404,
    )
    _audit(request, "shop_product_update", target=str(product_id), detail=payload.label)
    return {"updated": True}


@app.delete("/api/admin/shop/products/{product_id}")
def remove_shop_product(
    product_id: int,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(lambda: delete_shop_product(settings.database_path, product_id), status_code=404)
    _audit(request, "shop_product_delete", target=str(product_id))
    return {"deleted": True}


@app.post("/api/admin/shop/combos")
def add_shop_combo(
    payload: ShopComboRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, int]:
    combo_id = _db_call(
        lambda: create_shop_combo(
            settings.database_path,
            key=payload.key,
            label=payload.label,
            price_cop=payload.price_cop,
            blurb=payload.blurb,
            active=payload.active,
            items=[item.model_dump() for item in payload.items],
        )
    )
    _audit(request, "shop_combo_create", target=str(combo_id), detail=payload.label)
    return {"id": combo_id}


@app.put("/api/admin/shop/combos/{combo_id}")
def edit_shop_combo(
    combo_id: int,
    payload: ShopComboRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(
        lambda: update_shop_combo(
            settings.database_path,
            combo_id,
            label=payload.label,
            price_cop=payload.price_cop,
            blurb=payload.blurb,
            active=payload.active,
            items=[item.model_dump() for item in payload.items],
        ),
        status_code=404,
    )
    _audit(request, "shop_combo_update", target=str(combo_id), detail=payload.label)
    return {"updated": True}


@app.delete("/api/admin/shop/combos/{combo_id}")
def remove_shop_combo(
    combo_id: int,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(lambda: delete_shop_combo(settings.database_path, combo_id), status_code=404)
    _audit(request, "shop_combo_delete", target=str(combo_id))
    return {"deleted": True}


@app.post("/api/admin/shop/discounts")
def add_shop_discount(
    payload: ShopDiscountRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, int]:
    discount_id = _db_call(
        lambda: create_shop_discount(
            settings.database_path,
            code=payload.code or payload.label,
            label=payload.label,
            discount_type=payload.discount_type,
            value=payload.value,
            active=payload.active,
            expires_at=payload.expires_at,
        )
    )
    _audit(request, "shop_discount_create", target=str(discount_id), detail=payload.code.upper())
    return {"id": discount_id}


@app.put("/api/admin/shop/discounts/{discount_id}")
def edit_shop_discount(
    discount_id: int,
    payload: ShopDiscountRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(
        lambda: update_shop_discount(
            settings.database_path,
            discount_id,
            label=payload.label,
            discount_type=payload.discount_type,
            value=payload.value,
            active=payload.active,
            expires_at=payload.expires_at,
        ),
        status_code=404,
    )
    _audit(request, "shop_discount_update", target=str(discount_id), detail=payload.label)
    return {"updated": True}


@app.delete("/api/admin/shop/discounts/{discount_id}")
def remove_shop_discount(
    discount_id: int,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(lambda: delete_shop_discount(settings.database_path, discount_id), status_code=404)
    _audit(request, "shop_discount_delete", target=str(discount_id))
    return {"deleted": True}


@app.post("/api/admin/shop/stock")
def add_shop_stock(
    payload: ShopStockRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, int]:
    if not payload.password.strip():
        raise HTTPException(status_code=400, detail="La contraseña es obligatoria.")
    stock_id = _db_call(
        lambda: create_shop_stock(
            settings.database_path,
            product_id=payload.product_id,
            login=payload.login,
            password=payload.password,
            notes=payload.notes,
            status=payload.status,
        )
    )
    _audit(request, "shop_stock_create", target=str(stock_id), detail=payload.login)
    return {"id": stock_id}


@app.put("/api/admin/shop/stock/{stock_id}")
def edit_shop_stock(
    stock_id: int,
    payload: ShopStockRequest,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(
        lambda: update_shop_stock(
            settings.database_path,
            stock_id,
            product_id=payload.product_id,
            login=payload.login,
            password=payload.password or None,
            notes=payload.notes,
            status=payload.status,
        ),
        status_code=404,
    )
    _audit(request, "shop_stock_update", target=str(stock_id), detail=payload.login)
    return {"updated": True}


@app.delete("/api/admin/shop/stock/{stock_id}")
def remove_shop_stock(
    stock_id: int,
    request: Request,
    _: dict = Depends(require_admin),
) -> dict[str, bool]:
    _db_call(lambda: delete_shop_stock(settings.database_path, stock_id), status_code=404)
    _audit(request, "shop_stock_delete", target=str(stock_id))
    return {"deleted": True}


@app.post("/api/lookup")
def lookup(payload: LookupRequest, request: Request) -> dict:
    platform = get_platform(settings.database_path, payload.platform)
    if platform is None:
        raise HTTPException(status_code=400, detail="La plataforma seleccionada no es válida.")
    if payload.code_type == "household" and platform.key != "netflix":
        raise HTTPException(
            status_code=400,
            detail="El código de hogar / TV solo está disponible para Netflix.",
        )
    ip = client_ip(request)
    limiter.hit(f"lookup:{ip}", settings.lookup_rate_limit, settings.lookup_rate_window_seconds)

    identifier = payload.identifier.strip()
    if len(digits_only(identifier)) < 7:
        raise HTTPException(status_code=400, detail="Ingresa un número de celular válido.")
    access = find_client_access(settings.database_path, platform.key, identifier)
    if access is None:
        raise HTTPException(
            status_code=403,
            detail="No encontramos una cuenta activa asociada a ese celular. Verifica el número.",
        )

    renewal = build_whatsapp_renewal(platform.label, identifier)
    if access["expired"]:
        record_lookup(settings.database_path, platform.key, identifier, False)
        return {
            "code": None,
            "link_url": None,
            "source": None,
            "expires_in": 0,
            "account_expires_at": access["expires_at"],
            "seconds_remaining": 0,
            "days_remaining": 0,
            "urgency": "red",
            "expired": True,
            "renewal": renewal,
            "message": (
                "Tu acceso venció (30 días desde la vinculación). "
                "Escribe al bot de WhatsApp para renovar y volver a consultar códigos."
            ),
        }

    try:
        if access.get("main_account_id") and access.get("main_email"):
            mailbox = credentials_from_main_account(
                {
                    "email": access["main_email"],
                    "password": access["main_password"],
                    "imap_host": access["imap_host"],
                    "imap_port": access["imap_port"],
                    "imap_folder": access["imap_folder"],
                }
            )
        else:
            mailbox = credentials_from_settings(settings)
        search_identifier = access["account_email"] if access.get("account_email") else identifier

        if payload.code_type == "household":
            return _lookup_household(
                settings=settings,
                platform=platform,
                identifier=identifier,
                search_identifier=search_identifier,
                mailbox=mailbox,
                access=access,
                renewal=renewal,
            )

        result = find_recent_code(settings, platform, search_identifier, mailbox)
        if result.code is None and "@" in search_identifier:
            local_part = search_identifier.split("@", 1)[0]
            if local_part and local_part != search_identifier:
                retry = find_recent_code(settings, platform, local_part, mailbox)
                if retry.code:
                    result = retry
                elif retry.near_miss_recipients and not result.near_miss_recipients:
                    result = retry
        code = result.code
    except (OSError, RuntimeError, UnicodeEncodeError, imaplib.IMAP4.error) as error:
        logger.warning("Fallo IMAP en lookup: %s", error)
        detail = (
            "El servicio de correo no está disponible. Intenta de nuevo en unos minutos."
            if settings.is_production
            else _imap_error_detail(error, bool(access.get("main_account_id")))
        )
        raise HTTPException(status_code=503, detail=detail) from error
    record_lookup(settings.database_path, platform.key, identifier, code is not None)
    response = {
        "code": code,
        "link_url": None,
        "source": "email" if code else None,
        "expires_in": settings.code_ttl_seconds,
        "account_expires_at": access["expires_at"],
        "seconds_remaining": access["seconds_remaining"],
        "days_remaining": access["days_remaining"],
        "urgency": access.get("urgency", "green"),
        "expired": False,
        "renewal": renewal,
    }
    if code is None:
        response["message"] = (
            "No se encontró código para tu correo asociado o tu cuenta ya venció."
        )
    return response


def _lookup_household(
    *,
    settings,
    platform,
    identifier: str,
    search_identifier: str,
    mailbox,
    access: dict,
    renewal: dict,
) -> dict:
    try:
        link_result = find_recent_household_link(settings, platform, search_identifier, mailbox)
        if link_result.link_url is None and "@" in search_identifier:
            local_part = search_identifier.split("@", 1)[0]
            if local_part and local_part != search_identifier:
                retry = find_recent_household_link(settings, platform, local_part, mailbox)
                if retry.link_url:
                    link_result = retry
                elif retry.near_miss_recipients and not link_result.near_miss_recipients:
                    link_result = retry
    except (OSError, RuntimeError, UnicodeEncodeError, imaplib.IMAP4.error) as error:
        logger.warning("Fallo IMAP en lookup hogar/TV: %s", error)
        detail = (
            "El servicio de correo no está disponible. Intenta de nuevo en unos minutos."
            if settings.is_production
            else _imap_error_detail(error, bool(access.get("main_account_id")))
        )
        raise HTTPException(status_code=503, detail=detail) from error

    base = {
        "expires_in": settings.code_ttl_seconds,
        "account_expires_at": access["expires_at"],
        "seconds_remaining": access["seconds_remaining"],
        "days_remaining": access["days_remaining"],
        "urgency": access.get("urgency", "green"),
        "expired": False,
        "renewal": renewal,
    }

    if not link_result.link_url:
        record_lookup(settings.database_path, platform.key, identifier, False)
        message = (
            "No se encontró código para tu correo asociado o tu cuenta ya venció."
        )
        return {
            **base,
            "code": None,
            "link_url": None,
            "source": None,
            "message": message,
        }

    resolved = resolve_household_code(link_result.link_url)
    found = bool(resolved.code)
    record_lookup(settings.database_path, platform.key, identifier, found)
    if resolved.code:
        return {
            **base,
            "code": resolved.code,
            "link_url": resolved.link_url,
            "source": resolved.source or "page",
        }
    return {
        **base,
        "code": None,
        "link_url": resolved.link_url or link_result.link_url,
        "source": "link",
        "message": (
            "Encontramos el correo, pero no pudimos leer el código automáticamente. "
            "Ábrelo en Netflix con el botón de abajo."
        ),
    }


def _imap_error_detail(error: Exception, using_main_account: bool) -> str:
    if isinstance(error, UnicodeEncodeError):
        return (
            "La búsqueda IMAP falló por caracteres no ASCII en el asunto. "
            "Se corrigió el filtro; reinicia el servidor e inténtalo de nuevo."
        )
    raw = str(error).casefold()
    if "application-specific password" in raw or "app password" in raw:
        return (
            "Gmail exige una contraseña de aplicación (no la clave normal). "
            "Créala en https://myaccount.google.com/apppasswords y pégala en la cuenta principal del admin."
        )
    if "invalid credentials" in raw or "authentication failed" in raw or "login" in raw:
        target = "la cuenta principal en el panel admin" if using_main_account else "IMAP_USERNAME / IMAP_PASSWORD en .env"
        return f"No se pudo iniciar sesión en el correo. Revisa las credenciales IMAP de {target}."
    if using_main_account:
        return "El servicio de correo no está disponible. Revisa host/usuario/contraseña de la cuenta principal."
    return "El servicio de correo no está disponible. Revisa las credenciales IMAP en .env."
