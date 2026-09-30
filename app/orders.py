"""Pedidos de tienda: comprobante Bre-B, autorización y entrega de cuentas."""

from __future__ import annotations

import json
import mimetypes
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.database import (
    _open,
    assign_account,
    create_account,
    digits_only,
    get_or_create_client,
)
from app.shop import format_cop
from app.shop_store import apply_discount_amount, ensure_shop_schema, resolve_shop_discount

RECEIPT_DIR = Path("data/receipts")
ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def ensure_orders_schema(connection: sqlite3.Connection) -> None:
    ensure_shop_schema(connection)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shop_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,
            payer_name TEXT NOT NULL,
            whatsapp TEXT NOT NULL,
            items_json TEXT NOT NULL,
            subtotal INTEGER NOT NULL,
            savings INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL,
            discount_code TEXT,
            receipt_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            stock_ids_json TEXT,
            created_at TEXT NOT NULL,
            decided_at TEXT
        )
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(shop_orders)").fetchall()}
    if "payment_method" not in columns:
        connection.execute("ALTER TABLE shop_orders ADD COLUMN payment_method TEXT")


def save_receipt(content: bytes, content_type: str) -> str:
    ext = ALLOWED_TYPES.get((content_type or "").split(";")[0].strip().lower())
    if ext is None:
        raise ValueError("El comprobante debe ser una imagen JPG, PNG o WEBP.")
    if len(content) < 32 or len(content) > 6 * 1024 * 1024:
        raise ValueError("La imagen debe pesar entre unos bytes y 6 MB.")
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(16)}{ext}"
    path = RECEIPT_DIR / name
    path.write_bytes(content)
    return str(path).replace("\\", "/")


def _expand_units(path: str, items: list[dict]) -> list[dict]:
    units: list[dict] = []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        ensure_orders_schema(connection)
        for item in items:
            kind = item.get("kind") or "product"
            qty = int(item.get("qty") or 0)
            key = str(item.get("key") or "").strip()
            if qty < 1 or qty > 20 or not key:
                raise ValueError("El carrito no es válido.")
            if kind == "combo":
                combo = connection.execute(
                    "SELECT id, label FROM shop_combos WHERE key = ? AND active = 1",
                    (key,),
                ).fetchone()
                if combo is None:
                    raise ValueError("Uno de los combos ya no está disponible.")
                parts = connection.execute(
                    """
                    SELECT p.key, p.label, ci.quantity
                    FROM shop_combo_items ci
                    JOIN shop_products p ON p.id = ci.product_id
                    WHERE ci.combo_id = ?
                    """,
                    (combo["id"],),
                ).fetchall()
                if not parts:
                    raise ValueError(f"El combo {combo['label']} no tiene productos.")
                for _ in range(qty):
                    for part in parts:
                        for _unit in range(int(part["quantity"])):
                            units.append({"key": part["key"], "label": part["label"]})
            else:
                product = connection.execute(
                    "SELECT key, label, price_cop FROM shop_products WHERE key = ? AND active = 1",
                    (key,),
                ).fetchone()
                if product is None:
                    raise ValueError("Uno de los productos ya no está disponible.")
                for _ in range(qty):
                    units.append({"key": product["key"], "label": product["label"]})
    return units


def _line_subtotal(path: str, items: list[dict]) -> int:
    total = 0
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        ensure_orders_schema(connection)
        for item in items:
            key = str(item.get("key") or "")
            qty = int(item.get("qty") or 0)
            if item.get("kind") == "combo":
                row = connection.execute(
                    "SELECT price_cop FROM shop_combos WHERE key = ? AND active = 1",
                    (key,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT price_cop FROM shop_products WHERE key = ? AND active = 1",
                    (key,),
                ).fetchone()
            if row is None:
                raise ValueError("No se pudo calcular el total.")
            total += int(row["price_cop"]) * qty
    return total


def create_order(
    path: str,
    *,
    payer_name: str,
    whatsapp: str,
    items: list[dict],
    discount_code: str,
    receipt_path: str,
    payment_method: str = "",
) -> dict:
    name = payer_name.strip()
    phone_digits = digits_only(whatsapp)
    if len(name) < 3:
        raise ValueError("Escribe el nombre del titular de la cuenta.")
    if len(phone_digits) < 10:
        raise ValueError("Escribe un WhatsApp válido.")
    units = _expand_units(path, items)
    subtotal = _line_subtotal(path, items)
    discount = resolve_shop_discount(path, discount_code) if discount_code else None
    total, savings = apply_discount_amount(subtotal, discount)
    if total <= 0:
        raise ValueError("El total del pedido no es válido.")

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        ensure_orders_schema(connection)
        needed: dict[str, int] = {}
        for unit in units:
            needed[unit["key"]] = needed.get(unit["key"], 0) + 1
        for key in needed:
            available = connection.execute(
                """
                SELECT COUNT(*) FROM shop_stock s
                JOIN shop_products p ON p.id = s.product_id
                WHERE p.key = ? AND s.status = 'available'
                """,
                (key,),
            ).fetchone()[0]
            if available < 1:
                label = next(unit["label"] for unit in units if unit["key"] == key)
                raise ValueError(f"No hay cuentas disponibles de {label}.")
        token = secrets.token_urlsafe(24)
        cursor = connection.execute(
            """
            INSERT INTO shop_orders (
                token, payer_name, whatsapp, items_json, subtotal, savings, total,
                discount_code, receipt_path, payment_method, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                token,
                name,
                phone_digits,
                json.dumps(items, ensure_ascii=False),
                subtotal,
                savings,
                total,
                discount["code"] if discount else None,
                receipt_path,
                payment_method.strip() or None,
                datetime.now(UTC).isoformat(),
            ),
        )
        connection.commit()
        order_id = int(cursor.lastrowid)
    return {"id": order_id, "token": token, "total": total}


def get_order(path: str, token: str) -> dict | None:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        ensure_orders_schema(connection)
        row = connection.execute(
            "SELECT * FROM shop_orders WHERE token = ?",
            (token,),
        ).fetchone()
    if row is None:
        return None
    order = dict(row)
    order["items"] = json.loads(order["items_json"] or "[]")
    return order


def receipt_file(path: str, token: str) -> tuple[Path, str] | None:
    order = get_order(path, token)
    if order is None:
        return None
    file_path = Path(order["receipt_path"])
    if not file_path.is_file():
        return None
    media = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return file_path, media


def _summary_lines(order: dict) -> str:
    lines = []
    for item in order["items"]:
        kind = " (combo)" if item.get("kind") == "combo" else ""
        lines.append(f"- {item.get('label', item.get('key'))}{kind} x{item.get('qty')}")
    return "\n".join(lines)


def admin_whatsapp_text(order: dict, review_url: str, receipt_url: str) -> str:
    method = order.get("payment_method") or "No indicada"
    return (
        f"Nuevo pago · pedido #{order['id']}\n"
        f"Forma de pago: {method}\n"
        f"Titular: {order['payer_name']}\n"
        f"WhatsApp: {order['whatsapp']}\n"
        f"Total: {format_cop(int(order['total']))}\n"
        f"{_summary_lines(order)}\n\n"
        f"Comprobante: {receipt_url}\n"
        f"Autorizar o rechazar: {review_url}"
    )


def _claim_stock(path: str, token: str) -> tuple[dict, list[dict]]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        ensure_orders_schema(connection)
        row = connection.execute(
            "SELECT * FROM shop_orders WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None:
            raise ValueError("El pedido no existe.")
        if row["status"] != "pending":
            raise ValueError("Este pedido ya fue respondido.")
        items = json.loads(row["items_json"] or "[]")
        units = _expand_units(path, items)
        claimed: list[dict] = []
        seen_keys: set[str] = set()
        for unit in units:
            if unit["key"] in seen_keys:
                continue
            seen_keys.add(unit["key"])
            pool = connection.execute(
                """
                SELECT s.id, s.login, s.password, s.sale_count, p.key, p.label
                FROM shop_stock s
                JOIN shop_products p ON p.id = s.product_id
                WHERE p.key = ? AND s.status = 'available'
                ORDER BY s.id ASC
                """,
                (unit["key"],),
            ).fetchall()
            if not pool:
                raise ValueError(f"Ya no hay stock de {unit['label']}.")
            total_sales = sum(int(item["sale_count"] or 0) for item in pool)
            stock = pool[(total_sales // 2) % len(pool)]
            connection.execute(
                "UPDATE shop_stock SET sale_count = COALESCE(sale_count, 0) + 1 WHERE id = ?",
                (stock["id"],),
            )
            claimed.append(
                {
                    "stock_id": int(stock["id"]),
                    "key": stock["key"],
                    "label": stock["label"],
                    "login": stock["login"],
                    "password": _open(stock["password"]),
                }
            )
        connection.execute(
            """
            UPDATE shop_orders
            SET status = 'approved', stock_ids_json = ?, decided_at = ?
            WHERE token = ? AND status = 'pending'
            """,
            (
                json.dumps([item["stock_id"] for item in claimed]),
                datetime.now(UTC).isoformat(),
                token,
            ),
        )
        connection.commit()
        order = dict(row)
        order["status"] = "approved"
        order["items"] = items
    return order, claimed


def _link_streaming(path: str, client_id: int, item: dict) -> str:
    login = item["login"].strip()
    password = item["password"]
    platform = item["key"]
    if "@" not in login:
        return "entregada (sin correo para asociar códigos)"
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        match = connection.execute(
            """
            SELECT a.id
            FROM streaming_accounts a
            WHERE a.platform = ? AND lower(a.email) = lower(?)
              AND NOT EXISTS (
                SELECT 1 FROM client_accounts ca WHERE ca.account_id = a.id
              )
            ORDER BY a.id ASC
            LIMIT 1
            """,
            (platform, login),
        ).fetchone()
    account_id = int(match["id"]) if match else None
    if account_id is None:
        expires = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        account_id = create_account(
            path,
            platform,
            item["label"],
            login,
            password,
            expires,
        )
    try:
        assign_account(path, client_id, account_id)
    except ValueError:
        return "entregada (el cliente ya tenía esta plataforma)"
    return "asociada 30 días"


def approve_order(path: str, token: str) -> dict:
    order, claimed = _claim_stock(path, token)
    stock_ids = [item["stock_id"] for item in claimed]
    try:
        client_id = get_or_create_client(path, order["payer_name"], order["whatsapp"])
        delivered = []
        for item in claimed:
            note = _link_streaming(path, client_id, item)
            delivered.append({**item, "note": note})
    except Exception:
        with sqlite3.connect(path) as connection:
            connection.executemany(
                """
                UPDATE shop_stock
                SET sale_count = CASE WHEN sale_count > 0 THEN sale_count - 1 ELSE 0 END
                WHERE id = ?
                """,
                [(stock_id,) for stock_id in stock_ids],
            )
            connection.execute(
                """
                UPDATE shop_orders
                SET status = 'pending', stock_ids_json = NULL, decided_at = NULL
                WHERE token = ?
                """,
                (token,),
            )
            connection.commit()
        raise
    return {"order": order, "client_id": client_id, "accounts": delivered}


def reject_order(path: str, token: str) -> dict:
    with sqlite3.connect(path) as connection:
        ensure_orders_schema(connection)
        cursor = connection.execute(
            """
            UPDATE shop_orders
            SET status = 'rejected', decided_at = ?
            WHERE token = ? AND status = 'pending'
            """,
            (datetime.now(UTC).isoformat(), token),
        )
        connection.commit()
        if cursor.rowcount == 0:
            order = get_order(path, token)
            if order is None:
                raise ValueError("El pedido no existe.")
            raise ValueError("Este pedido ya fue respondido.")
    order = get_order(path, token)
    return {"order": order}


def credentials_message(payer_name: str, accounts: list[dict]) -> str:
    lines = [f"Hola {payer_name}, tu pago fue autorizado. Estas son tus cuentas:", ""]
    for item in accounts:
        lines.append(item["label"])
        lines.append(f"Correo: {item['login']}")
        lines.append(f"Contraseña: {item['password']}")
        lines.append("")
    lines.append("Con tu WhatsApp puedes pedir el código en Central Code durante 30 días.")
    return "\n".join(lines).strip()


def load_approved_accounts(path: str, order: dict) -> list[dict]:
    raw = order.get("stock_ids_json")
    if not raw:
        return []
    stock_ids = json.loads(raw)
    accounts = []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        for stock_id in stock_ids:
            row = connection.execute(
                """
                SELECT s.login, s.password, p.label, p.key
                FROM shop_stock s
                JOIN shop_products p ON p.id = s.product_id
                WHERE s.id = ?
                """,
                (stock_id,),
            ).fetchone()
            if row is None:
                continue
            accounts.append(
                {
                    "label": row["label"],
                    "key": row["key"],
                    "login": row["login"],
                    "password": _open(row["password"]),
                }
            )
    return accounts
