"""Persistencia de la tienda pública: productos, combos, descuentos y stock."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime

from app.shop import SHOP_CATALOG, format_cop


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _slug(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:48] or "item"


def ensure_shop_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shop_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            price_cop INTEGER NOT NULL,
            blurb TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'General',
            active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            otp_senders TEXT NOT NULL DEFAULT '',
            otp_subjects TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(shop_products)").fetchall()}
    if "otp_senders" not in columns:
        connection.execute("ALTER TABLE shop_products ADD COLUMN otp_senders TEXT NOT NULL DEFAULT ''")
    if "otp_subjects" not in columns:
        connection.execute("ALTER TABLE shop_products ADD COLUMN otp_subjects TEXT NOT NULL DEFAULT ''")
    # Columna antigua de vínculo (ya no se usa).
    if "platform_key" not in columns:
        connection.execute("ALTER TABLE shop_products ADD COLUMN platform_key TEXT")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shop_combos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            price_cop INTEGER NOT NULL,
            blurb TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shop_combo_items (
            combo_id INTEGER NOT NULL REFERENCES shop_combos(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES shop_products(id) ON DELETE CASCADE,
            quantity INTEGER NOT NULL DEFAULT 1,
            UNIQUE(combo_id, product_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shop_discounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            discount_type TEXT NOT NULL,
            value REAL NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            expires_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shop_stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES shop_products(id) ON DELETE CASCADE,
            login TEXT NOT NULL,
            password TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'available',
            created_at TEXT NOT NULL
        )
        """
    )


def seed_shop_products(path: str) -> None:
    from app.platforms import OTP_SENDER_DEFAULTS

    with sqlite3.connect(path) as connection:
        ensure_shop_schema(connection)
        count = connection.execute("SELECT COUNT(*) FROM shop_products").fetchone()[0]
        if not count:
            for index, product in enumerate(SHOP_CATALOG):
                senders = ",".join(OTP_SENDER_DEFAULTS.get(product.key, ()))
                connection.execute(
                    """
                    INSERT INTO shop_products
                        (key, label, price_cop, blurb, category, active, sort_order,
                         otp_senders, otp_subjects, created_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?, '', ?)
                    """,
                    (
                        product.key,
                        product.label,
                        product.price_cop,
                        product.blurb,
                        product.category,
                        index,
                        senders,
                        _now(),
                    ),
                )
        # Rellena y completa remitentes OTP en productos conocidos.
        rows = connection.execute(
            "SELECT key, otp_senders FROM shop_products WHERE key IS NOT NULL"
        ).fetchall()
        current = {row[0]: (row[1] or "").strip() for row in rows}
        for key, senders in OTP_SENDER_DEFAULTS.items():
            existing = [
                part.strip()
                for part in current.get(key, "").split(",")
                if part.strip()
            ]
            merged = list(existing)
            for sender in senders:
                if sender.casefold() not in {item.casefold() for item in merged}:
                    merged.append(sender)
            if not merged or merged == existing:
                if merged == existing and existing:
                    continue
            connection.execute(
                "UPDATE shop_products SET otp_senders = ? WHERE key = ?",
                (",".join(merged), key),
            )
        connection.commit()


def _product_row(row: sqlite3.Row, *, stock_available: int | None = None) -> dict:
    keys = set(row.keys())
    item = {
        "id": row["id"],
        "key": row["key"],
        "label": row["label"],
        "price_cop": int(row["price_cop"]),
        "price_label": format_cop(int(row["price_cop"])),
        "blurb": row["blurb"] or "",
        "category": row["category"] or "General",
        "active": bool(row["active"]),
        "sort_order": int(row["sort_order"] or 0),
        "otp_senders": (row["otp_senders"] if "otp_senders" in keys else "") or "",
        "otp_subjects": (row["otp_subjects"] if "otp_subjects" in keys else "") or "",
    }
    if stock_available is not None:
        item["stock_available"] = stock_available
    return item


def list_shop_products_admin(path: str) -> list[dict]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        ensure_shop_schema(connection)
        rows = connection.execute(
            """
            SELECT p.*,
                (
                    SELECT COUNT(*) FROM shop_stock s
                    WHERE s.product_id = p.id AND s.status = 'available'
                ) AS stock_available
            FROM shop_products p
            ORDER BY p.sort_order ASC, p.label ASC
            """
        ).fetchall()
    return [_product_row(row, stock_available=int(row["stock_available"])) for row in rows]


def list_shop_products_public(path: str) -> list[dict]:
    return [
        {
            "key": item["key"],
            "label": item["label"],
            "price_cop": item["price_cop"],
            "blurb": item["blurb"],
            "category": item["category"],
            "kind": "product",
            "stock_available": item.get("stock_available") or 0,
        }
        for item in list_shop_products_admin(path)
        if item["active"]
    ]


def get_shop_product(path: str, product_id: int) -> dict | None:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        ensure_shop_schema(connection)
        row = connection.execute(
            "SELECT * FROM shop_products WHERE id = ?",
            (product_id,),
        ).fetchone()
    return _product_row(row) if row else None


def get_shop_product_by_key(path: str, key: str) -> dict | None:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        ensure_shop_schema(connection)
        row = connection.execute(
            "SELECT * FROM shop_products WHERE key = ?",
            (key.strip(),),
        ).fetchone()
    return _product_row(row) if row else None


def create_shop_product(
    path: str,
    *,
    key: str,
    label: str,
    price_cop: int,
    blurb: str = "",
    category: str = "General",
    active: bool = True,
    otp_senders: str = "",
    otp_subjects: str = "",
) -> int:
    product_key = _slug(key or label)
    if price_cop < 0:
        raise ValueError("El precio no puede ser negativo.")
    with sqlite3.connect(path) as connection:
        ensure_shop_schema(connection)
        try:
            cursor = connection.execute(
                """
                INSERT INTO shop_products
                    (key, label, price_cop, blurb, category, active, sort_order,
                     otp_senders, otp_subjects, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    product_key,
                    label.strip(),
                    int(price_cop),
                    blurb.strip(),
                    category.strip() or "General",
                    1 if active else 0,
                    (otp_senders or "").strip(),
                    (otp_subjects or "").strip(),
                    _now(),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError as error:
            raise ValueError("Ya existe un producto con esa clave.") from error


def update_shop_product(
    path: str,
    product_id: int,
    *,
    label: str,
    price_cop: int,
    blurb: str = "",
    category: str = "General",
    active: bool = True,
    otp_senders: str = "",
    otp_subjects: str = "",
) -> None:
    if price_cop < 0:
        raise ValueError("El precio no puede ser negativo.")
    with sqlite3.connect(path) as connection:
        ensure_shop_schema(connection)
        cursor = connection.execute(
            """
            UPDATE shop_products
            SET label = ?, price_cop = ?, blurb = ?, category = ?, active = ?,
                otp_senders = ?, otp_subjects = ?
            WHERE id = ?
            """,
            (
                label.strip(),
                int(price_cop),
                blurb.strip(),
                category.strip() or "General",
                1 if active else 0,
                (otp_senders or "").strip(),
                (otp_subjects or "").strip(),
                product_id,
            ),
        )
        connection.commit()
        if cursor.rowcount == 0:
            raise ValueError("Producto no encontrado.")


def delete_shop_product(path: str, product_id: int) -> None:
    with sqlite3.connect(path) as connection:
        ensure_shop_schema(connection)
        cursor = connection.execute("DELETE FROM shop_products WHERE id = ?", (product_id,))
        connection.commit()
        if cursor.rowcount == 0:
            raise ValueError("Producto no encontrado.")


def _combo_items(connection: sqlite3.Connection, combo_id: int) -> list[dict]:
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT ci.quantity, p.id AS product_id, p.key, p.label, p.price_cop
        FROM shop_combo_items ci
        JOIN shop_products p ON p.id = ci.product_id
        WHERE ci.combo_id = ?
        ORDER BY p.label ASC
        """,
        (combo_id,),
    ).fetchall()
    return [
        {
            "product_id": row["product_id"],
            "key": row["key"],
            "label": row["label"],
            "price_cop": int(row["price_cop"]),
            "quantity": int(row["quantity"]),
        }
        for row in rows
    ]


def list_shop_combos(path: str, *, active_only: bool = False) -> list[dict]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        ensure_shop_schema(connection)
        query = "SELECT * FROM shop_combos"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY label ASC"
        rows = connection.execute(query).fetchall()
        result = []
        for row in rows:
            items = _combo_items(connection, row["id"])
            result.append(
                {
                    "id": row["id"],
                    "key": row["key"],
                    "label": row["label"],
                    "price_cop": int(row["price_cop"]),
                    "price_label": format_cop(int(row["price_cop"])),
                    "blurb": row["blurb"] or "",
                    "active": bool(row["active"]),
                    "items": items,
                    "kind": "combo",
                }
            )
        return result


def create_shop_combo(
    path: str,
    *,
    key: str,
    label: str,
    price_cop: int,
    blurb: str = "",
    active: bool = True,
    items: list[dict],
) -> int:
    if price_cop < 0:
        raise ValueError("El precio no puede ser negativo.")
    if not items:
        raise ValueError("El combo debe incluir al menos un producto.")
    combo_key = _slug(key or label)
    with sqlite3.connect(path) as connection:
        ensure_shop_schema(connection)
        try:
            cursor = connection.execute(
                """
                INSERT INTO shop_combos (key, label, price_cop, blurb, active, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    combo_key,
                    label.strip(),
                    int(price_cop),
                    blurb.strip(),
                    1 if active else 0,
                    _now(),
                ),
            )
            combo_id = int(cursor.lastrowid)
            for item in items:
                product_id = int(item["product_id"])
                quantity = max(1, int(item.get("quantity") or 1))
                connection.execute(
                    """
                    INSERT INTO shop_combo_items (combo_id, product_id, quantity)
                    VALUES (?, ?, ?)
                    """,
                    (combo_id, product_id, quantity),
                )
            connection.commit()
            return combo_id
        except sqlite3.IntegrityError as error:
            raise ValueError("Ya existe un combo con esa clave o productos inválidos.") from error


def update_shop_combo(
    path: str,
    combo_id: int,
    *,
    label: str,
    price_cop: int,
    blurb: str = "",
    active: bool = True,
    items: list[dict],
) -> None:
    if price_cop < 0:
        raise ValueError("El precio no puede ser negativo.")
    if not items:
        raise ValueError("El combo debe incluir al menos un producto.")
    with sqlite3.connect(path) as connection:
        ensure_shop_schema(connection)
        cursor = connection.execute(
            """
            UPDATE shop_combos
            SET label = ?, price_cop = ?, blurb = ?, active = ?
            WHERE id = ?
            """,
            (label.strip(), int(price_cop), blurb.strip(), 1 if active else 0, combo_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Combo no encontrado.")
        connection.execute("DELETE FROM shop_combo_items WHERE combo_id = ?", (combo_id,))
        for item in items:
            connection.execute(
                """
                INSERT INTO shop_combo_items (combo_id, product_id, quantity)
                VALUES (?, ?, ?)
                """,
                (combo_id, int(item["product_id"]), max(1, int(item.get("quantity") or 1))),
            )
        connection.commit()


def delete_shop_combo(path: str, combo_id: int) -> None:
    with sqlite3.connect(path) as connection:
        ensure_shop_schema(connection)
        connection.execute("DELETE FROM shop_combo_items WHERE combo_id = ?", (combo_id,))
        cursor = connection.execute("DELETE FROM shop_combos WHERE id = ?", (combo_id,))
        connection.commit()
        if cursor.rowcount == 0:
            raise ValueError("Combo no encontrado.")


def list_shop_discounts(path: str) -> list[dict]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        ensure_shop_schema(connection)
        rows = connection.execute(
            "SELECT * FROM shop_discounts ORDER BY created_at DESC"
        ).fetchall()
    return [
        {
            "id": row["id"],
            "code": row["code"],
            "label": row["label"],
            "discount_type": row["discount_type"],
            "value": float(row["value"]),
            "active": bool(row["active"]),
            "expires_at": row["expires_at"],
        }
        for row in rows
    ]


def create_shop_discount(
    path: str,
    *,
    code: str,
    label: str,
    discount_type: str,
    value: float,
    active: bool = True,
    expires_at: str | None = None,
) -> int:
    code_clean = code.strip().upper()
    if not code_clean:
        raise ValueError("El código es obligatorio.")
    if discount_type not in {"percent", "fixed"}:
        raise ValueError("Tipo de descuento inválido.")
    if value <= 0:
        raise ValueError("El valor del descuento debe ser mayor a 0.")
    if discount_type == "percent" and value > 100:
        raise ValueError("El porcentaje no puede superar 100.")
    with sqlite3.connect(path) as connection:
        ensure_shop_schema(connection)
        try:
            cursor = connection.execute(
                """
                INSERT INTO shop_discounts
                    (code, label, discount_type, value, active, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code_clean,
                    label.strip() or code_clean,
                    discount_type,
                    float(value),
                    1 if active else 0,
                    expires_at or None,
                    _now(),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError as error:
            raise ValueError("Ya existe un descuento con ese código.") from error


def update_shop_discount(
    path: str,
    discount_id: int,
    *,
    label: str,
    discount_type: str,
    value: float,
    active: bool = True,
    expires_at: str | None = None,
) -> None:
    if discount_type not in {"percent", "fixed"}:
        raise ValueError("Tipo de descuento inválido.")
    if value <= 0:
        raise ValueError("El valor del descuento debe ser mayor a 0.")
    if discount_type == "percent" and value > 100:
        raise ValueError("El porcentaje no puede superar 100.")
    with sqlite3.connect(path) as connection:
        ensure_shop_schema(connection)
        cursor = connection.execute(
            """
            UPDATE shop_discounts
            SET label = ?, discount_type = ?, value = ?, active = ?, expires_at = ?
            WHERE id = ?
            """,
            (
                label.strip(),
                discount_type,
                float(value),
                1 if active else 0,
                expires_at or None,
                discount_id,
            ),
        )
        connection.commit()
        if cursor.rowcount == 0:
            raise ValueError("Descuento no encontrado.")


def delete_shop_discount(path: str, discount_id: int) -> None:
    with sqlite3.connect(path) as connection:
        ensure_shop_schema(connection)
        cursor = connection.execute("DELETE FROM shop_discounts WHERE id = ?", (discount_id,))
        connection.commit()
        if cursor.rowcount == 0:
            raise ValueError("Descuento no encontrado.")


def resolve_shop_discount(path: str, code: str) -> dict | None:
    code_clean = (code or "").strip().upper()
    if not code_clean:
        return None
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        ensure_shop_schema(connection)
        row = connection.execute(
            "SELECT * FROM shop_discounts WHERE code = ?",
            (code_clean,),
        ).fetchone()
    if not row or not row["active"]:
        return None
    if row["expires_at"]:
        try:
            expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires < datetime.now(UTC):
                return None
        except ValueError:
            pass
    return {
        "code": row["code"],
        "label": row["label"],
        "discount_type": row["discount_type"],
        "value": float(row["value"]),
    }


def apply_discount_amount(subtotal: int, discount: dict | None) -> tuple[int, int]:
    if not discount or subtotal <= 0:
        return subtotal, 0
    if discount["discount_type"] == "percent":
        savings = int(round(subtotal * (float(discount["value"]) / 100.0)))
    else:
        savings = int(round(float(discount["value"])))
    savings = max(0, min(subtotal, savings))
    return subtotal - savings, savings


def list_shop_stock(path: str) -> list[dict]:
    from app.database import _open

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        ensure_shop_schema(connection)
        rows = connection.execute(
            """
            SELECT s.*, p.label AS product_label, p.key AS product_key
            FROM shop_stock s
            JOIN shop_products p ON p.id = s.product_id
            ORDER BY s.id DESC
            """
        ).fetchall()
    return [
        {
            "id": row["id"],
            "product_id": row["product_id"],
            "product_key": row["product_key"],
            "product_label": row["product_label"],
            "login": row["login"],
            "password": _open(row["password"]),
            "notes": row["notes"] or "",
            "status": row["status"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def create_shop_stock(
    path: str,
    *,
    product_id: int,
    login: str,
    password: str,
    notes: str = "",
    status: str = "available",
) -> int:
    from app.database import _seal

    if status not in {"available", "sold", "reserved"}:
        raise ValueError("Estado de stock inválido.")
    if not login.strip() or not password.strip():
        raise ValueError("Usuario y contraseña son obligatorios.")
    with sqlite3.connect(path) as connection:
        ensure_shop_schema(connection)
        exists = connection.execute(
            "SELECT id FROM shop_products WHERE id = ?",
            (product_id,),
        ).fetchone()
        if not exists:
            raise ValueError("Producto no encontrado.")
        cursor = connection.execute(
            """
            INSERT INTO shop_stock (product_id, login, password, notes, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                login.strip(),
                _seal(password),
                notes.strip(),
                status,
                _now(),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def update_shop_stock(
    path: str,
    stock_id: int,
    *,
    product_id: int,
    login: str,
    password: str | None,
    notes: str = "",
    status: str = "available",
) -> None:
    from app.database import _seal

    if status not in {"available", "sold", "reserved"}:
        raise ValueError("Estado de stock inválido.")
    with sqlite3.connect(path) as connection:
        ensure_shop_schema(connection)
        if password and password.strip():
            cursor = connection.execute(
                """
                UPDATE shop_stock
                SET product_id = ?, login = ?, password = ?, notes = ?, status = ?
                WHERE id = ?
                """,
                (
                    product_id,
                    login.strip(),
                    _seal(password),
                    notes.strip(),
                    status,
                    stock_id,
                ),
            )
        else:
            cursor = connection.execute(
                """
                UPDATE shop_stock
                SET product_id = ?, login = ?, notes = ?, status = ?
                WHERE id = ?
                """,
                (product_id, login.strip(), notes.strip(), status, stock_id),
            )
        if cursor.rowcount == 0:
            raise ValueError("Cuenta de stock no encontrada.")
        connection.commit()


def delete_shop_stock(path: str, stock_id: int) -> None:
    with sqlite3.connect(path) as connection:
        ensure_shop_schema(connection)
        cursor = connection.execute("DELETE FROM shop_stock WHERE id = ?", (stock_id,))
        connection.commit()
        if cursor.rowcount == 0:
            raise ValueError("Cuenta de stock no encontrada.")


def shop_admin_bundle(path: str) -> dict:
    products = list_shop_products_admin(path)
    combos = list_shop_combos(path)
    discounts = list_shop_discounts(path)
    stock = list_shop_stock(path)
    return {
        "products": products,
        "combos": combos,
        "discounts": discounts,
        "stock": stock,
        "summary": {
            "products": len(products),
            "active_products": sum(1 for p in products if p["active"]),
            "combos": len(combos),
            "discounts": len(discounts),
            "stock_available": sum(1 for s in stock if s["status"] == "available"),
            "stock_total": len(stock),
        },
    }
