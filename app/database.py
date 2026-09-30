import hashlib
import os
import sqlite3
from datetime import UTC, datetime, timedelta

# Días de acceso a códigos OTP desde la fecha de vinculación cliente↔cuenta.
LINK_ACCESS_DAYS = 30

_fernet = None


def configure_encryption(fernet) -> None:
    global _fernet
    _fernet = fernet


def _seal(value: str) -> str:
    if not value or _fernet is None:
        return value
    from app.security import ENC_PREFIX, encrypt_secret

    if value.startswith(ENC_PREFIX):
        return value
    return encrypt_secret(_fernet, value)


def _open(value: str) -> str:
    if not value or _fernet is None:
        return value
    from app.security import decrypt_secret

    return decrypt_secret(_fernet, value)


def init_database(path: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS lookups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                identifier_hash TEXT NOT NULL,
                found INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS main_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                password TEXT NOT NULL,
                domain TEXT NOT NULL,
                imap_host TEXT NOT NULL,
                imap_port INTEGER NOT NULL DEFAULT 993,
                imap_folder TEXT NOT NULL DEFAULT 'INBOX',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS streaming_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                password TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_accounts (
                client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                account_id INTEGER NOT NULL REFERENCES streaming_accounts(id) ON DELETE CASCADE,
                UNIQUE(client_id, account_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT,
                detail TEXT,
                ip_address TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        from app.shop_store import ensure_shop_schema

        ensure_shop_schema(connection)
        _ensure_column(connection, "streaming_accounts", "expires_at", "TEXT")
        _ensure_column(connection, "streaming_accounts", "main_account_id", "INTEGER")
        _ensure_column(connection, "streaming_accounts", "subdomain", "TEXT")
        _ensure_column(connection, "client_accounts", "assigned_at", "TEXT")
        _ensure_column(connection, "client_accounts", "expires_at", "TEXT")
        connection.execute(
            """
            UPDATE streaming_accounts
            SET expires_at = created_at
            WHERE expires_at IS NULL OR TRIM(expires_at) = ''
            """
        )
        connection.execute(
            """
            UPDATE client_accounts
            SET assigned_at = (
                SELECT sa.created_at FROM streaming_accounts sa WHERE sa.id = client_accounts.account_id
            )
            WHERE assigned_at IS NULL OR TRIM(assigned_at) = ''
            """
        )
        connection.commit()
        _backfill_link_expirations(connection)


def _link_expires_at(assigned_at: datetime) -> datetime:
    return assigned_at + timedelta(days=LINK_ACCESS_DAYS)


def _backfill_link_expirations(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT client_id, account_id, assigned_at, expires_at
        FROM client_accounts
        WHERE expires_at IS NULL OR TRIM(expires_at) = ''
        """
    ).fetchall()
    for client_id, account_id, assigned_at, _ in rows:
        assigned = _parse_expires_at(assigned_at) or datetime.now(UTC)
        expires = _link_expires_at(assigned)
        connection.execute(
            """
            UPDATE client_accounts
            SET expires_at = ?
            WHERE client_id = ? AND account_id = ?
            """,
            (expires.isoformat(), client_id, account_id),
        )
    if rows:
        connection.commit()


def migrate_plaintext_secrets(path: str) -> int:
    """Cifra contraseñas en claro ya guardadas. Devuelve cuántas actualizó."""
    from app.security import ENC_PREFIX

    updated = 0
    with sqlite3.connect(path) as connection:
        for table in ("main_accounts", "streaming_accounts", "shop_stock"):
            try:
                rows = connection.execute(f"SELECT id, password FROM {table}").fetchall()
            except sqlite3.OperationalError:
                continue
            for row_id, password in rows:
                if not password or str(password).startswith(ENC_PREFIX):
                    continue
                connection.execute(
                    f"UPDATE {table} SET password = ? WHERE id = ?",
                    (_seal(password), row_id),
                )
                updated += 1
        connection.commit()
    return updated


def list_audit_events(path: str, limit: int = 50) -> list[dict]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT id, actor, action, target, detail, ip_address, created_at
            FROM audit_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 200)),),
        ).fetchall()
    return [dict(row) for row in rows]


def record_audit(
    path: str,
    actor: str,
    action: str,
    *,
    target: str | None = None,
    detail: str | None = None,
    ip_address: str | None = None,
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO audit_events (actor, action, target, detail, ip_address, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                actor,
                action,
                target,
                detail,
                ip_address,
                datetime.now(UTC).isoformat(),
            ),
        )
        connection.commit()

def _ensure_column(connection: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def _parse_expires_at(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def digits_only(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def account_status(expires_at: str | None, now: datetime | None = None) -> dict:
    current = now or datetime.now(UTC)
    expires = _parse_expires_at(expires_at)
    if expires is None:
        return {
            "expires_at": expires_at,
            "expired": True,
            "seconds_remaining": 0,
            "days_remaining": 0,
            "urgency": "red",
        }
    seconds = int((expires - current).total_seconds())
    days_remaining = max((seconds + 86399) // 86400 if seconds > 0 else 0, 0)
    if days_remaining > 20:
        urgency = "green"
    elif days_remaining > 10:
        urgency = "yellow"
    else:
        urgency = "red"
    return {
        "expires_at": expires.isoformat(),
        "expired": seconds <= 0,
        "seconds_remaining": max(seconds, 0),
        "days_remaining": days_remaining,
        "urgency": urgency,
    }


def normalize_domain(domain: str) -> str:
    cleaned = domain.strip().casefold().removeprefix("https://").removeprefix("http://")
    cleaned = cleaned.split("/")[0].removeprefix("@")
    if "@" in cleaned:
        cleaned = cleaned.split("@", 1)[1]
    if not cleaned or "." not in cleaned:
        raise ValueError("El dominio no es válido. Ejemplo: gmail.com o rsd.tudominio.com")
    return cleaned


def normalize_alias_local(value: str) -> str:
    cleaned = value.strip().casefold()
    if "@" in cleaned:
        cleaned = cleaned.split("@", 1)[0]
    cleaned = "".join(character for character in cleaned if character.isalnum() or character in ".-_+")
    cleaned = cleaned.strip(".-_")
    if not cleaned:
        raise ValueError("El alias no es válido.")
    return cleaned


def build_alias_email(alias: str, domain: str) -> str:
    """Arma alias@dominio sin inventar prefijos. Respeta cinecolred+bat tal cual."""
    cleaned = alias.strip().casefold()
    if "@" in cleaned:
        return cleaned
    return f"{normalize_alias_local(cleaned)}@{normalize_domain(domain)}"


def record_lookup(path: str, platform: str, identifier: str, found: bool) -> None:
    identifier_hash = hashlib.sha256(identifier.casefold().encode("utf-8")).hexdigest()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO lookups (platform, identifier_hash, found, created_at) VALUES (?, ?, ?, ?)",
            (platform, identifier_hash, int(found), datetime.now(UTC).isoformat()),
        )
        connection.commit()


def list_main_accounts(path: str) -> list[dict]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT m.id, m.name, m.email, m.domain, m.imap_host, m.imap_port, m.imap_folder, m.created_at,
                   COUNT(a.id) AS linked_accounts
            FROM main_accounts m
            LEFT JOIN streaming_accounts a ON a.main_account_id = m.id
            GROUP BY m.id
            ORDER BY m.id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_main_account(path: str, main_account_id: int) -> dict | None:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT id, name, email, password, domain, imap_host, imap_port, imap_folder, created_at
            FROM main_accounts
            WHERE id = ?
            """,
            (main_account_id,),
        ).fetchone()
    if row is None:
        return None
    account = dict(row)
    account["password"] = _open(account["password"])
    return account


def normalize_main_mailbox(email: str, domain: str, imap_host: str, imap_folder: str) -> tuple[str, str, str, str]:
    cleaned_email = email.strip()
    if "@" not in cleaned_email:
        raise ValueError("El correo de la cuenta principal no es válido.")
    email_domain = cleaned_email.split("@", 1)[1].casefold()
    try:
        normalized_domain = normalize_domain(domain)
    except ValueError:
        normalized_domain = normalize_domain(email_domain)
    if email_domain in {"gmail.com", "googlemail.com"}:
        normalized_domain = email_domain
    cleaned_host = imap_host.strip()
    if not cleaned_host:
        raise ValueError("El host IMAP es obligatorio.")
    folder = (imap_folder or "INBOX").strip() or "INBOX"
    return cleaned_email, normalized_domain, cleaned_host, folder


def create_main_account(
    path: str,
    name: str,
    email: str,
    password: str,
    domain: str,
    imap_host: str,
    imap_port: int = 993,
    imap_folder: str = "INBOX",
) -> int:
    cleaned_email, normalized_domain, cleaned_host, folder = normalize_main_mailbox(
        email, domain, imap_host, imap_folder
    )
    with sqlite3.connect(path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO main_accounts (
                name, email, password, domain, imap_host, imap_port, imap_folder, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                cleaned_email,
                _seal(password),
                normalized_domain,
                cleaned_host,
                int(imap_port),
                folder,
                datetime.now(UTC).isoformat(),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def update_main_account_password(path: str, main_account_id: int, password: str) -> None:
    cleaned = password.strip()
    if not cleaned:
        raise ValueError("La contraseña IMAP no puede estar vacía.")
    with sqlite3.connect(path) as connection:
        cursor = connection.execute(
            "UPDATE main_accounts SET password = ? WHERE id = ?",
            (_seal(cleaned), main_account_id),
        )
        connection.commit()
        if cursor.rowcount == 0:
            raise ValueError("La cuenta principal no existe.")


def update_main_account(
    path: str,
    main_account_id: int,
    name: str,
    email: str,
    domain: str,
    imap_host: str,
    imap_port: int = 993,
    imap_folder: str = "INBOX",
    password: str | None = None,
) -> None:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        existing = connection.execute(
            "SELECT password FROM main_accounts WHERE id = ?",
            (main_account_id,),
        ).fetchone()
        if existing is None:
            raise ValueError("La cuenta principal no existe.")
        cleaned_email, normalized_domain, cleaned_host, folder = normalize_main_mailbox(
            email, domain, imap_host, imap_folder
        )
        new_password = _seal(password.strip()) if password and password.strip() else existing["password"]
        connection.execute(
            """
            UPDATE main_accounts
            SET name = ?, email = ?, password = ?, domain = ?, imap_host = ?, imap_port = ?, imap_folder = ?
            WHERE id = ?
            """,
            (
                name.strip(),
                cleaned_email,
                new_password,
                normalized_domain,
                cleaned_host,
                int(imap_port),
                folder,
                main_account_id,
            ),
        )
        connection.commit()


def delete_main_account(path: str, main_account_id: int) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        linked = connection.execute(
            "SELECT COUNT(*) FROM streaming_accounts WHERE main_account_id = ?",
            (main_account_id,),
        ).fetchone()[0]
        if linked:
            connection.execute(
                "UPDATE streaming_accounts SET main_account_id = NULL WHERE main_account_id = ?",
                (main_account_id,),
            )
        cursor = connection.execute("DELETE FROM main_accounts WHERE id = ?", (main_account_id,))
        connection.commit()
        if cursor.rowcount == 0:
            raise ValueError("La cuenta principal no existe.")


def _resolve_account_email(
    path: str,
    email: str,
    main_account_id: int | None,
    subdomain: str | None,
) -> tuple[str, str | None, int | None]:
    resolved_email = email.strip().casefold() if email.strip() else ""
    resolved_alias = None
    resolved_main_id = main_account_id
    alias_input = (subdomain or "").strip()

    if resolved_main_id is not None:
        main_account = get_main_account(path, resolved_main_id)
        if main_account is None:
            raise ValueError("La cuenta principal no existe.")
        if resolved_email and "@" in resolved_email:
            resolved_alias = normalize_alias_local(resolved_email.split("@", 1)[0])
        elif alias_input:
            resolved_email = build_alias_email(alias_input, main_account["domain"])
            resolved_alias = normalize_alias_local(resolved_email.split("@", 1)[0])
        else:
            raise ValueError(
                "Indica el correo alias que das a los clientes "
                "(ej. cinecolred+bat@gmail.com)."
            )
    elif alias_input:
        raise ValueError("Selecciona una cuenta principal para usar un alias.")
    elif not resolved_email or "@" not in resolved_email:
        raise ValueError("El correo de la cuenta no es válido.")
    else:
        resolved_alias = normalize_alias_local(resolved_email.split("@", 1)[0])
    return resolved_email, resolved_alias, resolved_main_id


def list_accounts(path: str) -> list[dict]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT a.id, a.platform, a.name, a.email, a.expires_at, a.created_at,
                   a.main_account_id, a.subdomain,
                   m.name AS main_account_name, m.domain AS main_account_domain
            FROM streaming_accounts a
            LEFT JOIN main_accounts m ON m.id = a.main_account_id
            ORDER BY a.id DESC
            """
        ).fetchall()
    result = []
    for row in rows:
        account = dict(row)
        account.update(account_status(account.get("expires_at")))
        result.append(account)
    return result


def list_clients(path: str) -> list[dict]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        clients = connection.execute(
            """
            SELECT id, name, phone, created_at
            FROM clients
            ORDER BY id DESC
            """
        ).fetchall()
        assignment_rows = connection.execute(
            """
            SELECT ca.client_id, ca.assigned_at, ca.expires_at AS link_expires_at,
                   a.id AS account_id, a.platform, a.name, a.email
            FROM client_accounts ca
            JOIN streaming_accounts a ON a.id = ca.account_id
            ORDER BY ca.client_id DESC, a.platform
            """
        ).fetchall()

    by_client: dict[int, list[dict]] = {}
    for row in assignment_rows:
        link_expires = row["link_expires_at"]
        assignment = {
            "account_id": row["account_id"],
            "platform": row["platform"],
            "name": row["name"],
            "email": row["email"],
            "expires_at": link_expires,
            "assigned_at": row["assigned_at"],
        }
        assignment.update(account_status(link_expires))
        by_client.setdefault(row["client_id"], []).append(assignment)

    result = []
    for client in clients:
        item = dict(client)
        item["assignments"] = by_client.get(client["id"], [])
        result.append(item)
    return result


def list_assignments(path: str) -> list[dict]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT ca.client_id, ca.assigned_at, ca.expires_at AS link_expires_at,
                   c.name AS client_name, c.phone AS client_phone,
                   a.id AS account_id, a.platform, a.name AS account_name,
                   a.email AS account_email
            FROM client_accounts ca
            JOIN clients c ON c.id = ca.client_id
            JOIN streaming_accounts a ON a.id = ca.account_id
            ORDER BY COALESCE(ca.assigned_at, '') DESC, ca.client_id DESC
            """
        ).fetchall()
    result = []
    for row in rows:
        link_expires = row["link_expires_at"]
        item = {
            "client_id": row["client_id"],
            "client_name": row["client_name"],
            "client_phone": row["client_phone"],
            "account_id": row["account_id"],
            "platform": row["platform"],
            "account_name": row["account_name"],
            "account_email": row["account_email"],
            "expires_at": link_expires,
            "assigned_at": row["assigned_at"],
        }
        item.update(account_status(link_expires))
        result.append(item)
    return result


def build_admin_summary(
    mains: list[dict],
    accounts: list[dict],
    clients: list[dict],
    assignments: list[dict],
) -> dict:
    urgency = {"green": 0, "yellow": 0, "red": 0}
    for account in accounts:
        key = account.get("urgency") or "red"
        if key in urgency:
            urgency[key] += 1
    return {
        "main_accounts": len(mains),
        "streaming_accounts": len(accounts),
        "clients": len(clients),
        "assignments": len(assignments),
        "urgency": urgency,
        "expiring_soon": [
            {
                "id": account["id"],
                "name": account["name"],
                "platform": account["platform"],
                "email": account["email"],
                "days_remaining": account["days_remaining"],
                "urgency": account["urgency"],
                "expires_at": account["expires_at"],
            }
            for account in accounts
            if account.get("urgency") in {"yellow", "red"}
        ][:8],
    }


def normalize_phone(phone: str) -> str:
    cleaned = phone.strip()
    digits = digits_only(cleaned)
    if len(digits) < 7:
        raise ValueError("El celular debe tener al menos 7 dígitos.")
    if cleaned.startswith("+"):
        return f"+{digits}"
    return digits


def create_account(
    path: str,
    platform: str,
    name: str,
    email: str,
    password: str,
    expires_at: str,
    main_account_id: int | None = None,
    subdomain: str | None = None,
) -> int:
    expires = _parse_expires_at(expires_at)
    if expires is None:
        raise ValueError("La fecha de vencimiento no es válida.")

    resolved_email, resolved_alias, resolved_main_id = _resolve_account_email(
        path, email, main_account_id, subdomain
    )

    with sqlite3.connect(path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO streaming_accounts (
                platform, name, email, password, expires_at, created_at, main_account_id, subdomain
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                platform,
                name,
                resolved_email,
                _seal(password),
                expires.isoformat(),
                datetime.now(UTC).isoformat(),
                resolved_main_id,
                resolved_alias,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def update_account(
    path: str,
    account_id: int,
    platform: str,
    name: str,
    email: str,
    expires_at: str,
    main_account_id: int | None = None,
    subdomain: str | None = None,
    password: str | None = None,
) -> None:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        existing = connection.execute(
            "SELECT password FROM streaming_accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
        if existing is None:
            raise ValueError("La cuenta no existe.")
        expires = _parse_expires_at(expires_at)
        if expires is None:
            raise ValueError("La fecha de vencimiento no es válida.")
        resolved_email, resolved_alias, resolved_main_id = _resolve_account_email(
            path, email, main_account_id, subdomain
        )
        new_password = _seal(password.strip()) if password and password.strip() else existing["password"]
        connection.execute(
            """
            UPDATE streaming_accounts
            SET platform = ?, name = ?, email = ?, password = ?, expires_at = ?,
                main_account_id = ?, subdomain = ?
            WHERE id = ?
            """,
            (
                platform,
                name,
                resolved_email,
                new_password,
                expires.isoformat(),
                resolved_main_id,
                resolved_alias,
                account_id,
            ),
        )
        connection.commit()


def delete_account(path: str, account_id: int) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM client_accounts WHERE account_id = ?", (account_id,))
        cursor = connection.execute("DELETE FROM streaming_accounts WHERE id = ?", (account_id,))
        connection.commit()
        if cursor.rowcount == 0:
            raise ValueError("La cuenta no existe.")


def update_account_expiration(path: str, account_id: int, expires_at: str) -> None:
    expires = _parse_expires_at(expires_at)
    if expires is None:
        raise ValueError("La fecha de vencimiento no es válida.")
    with sqlite3.connect(path) as connection:
        cursor = connection.execute(
            "UPDATE streaming_accounts SET expires_at = ? WHERE id = ?",
            (expires.isoformat(), account_id),
        )
        connection.commit()
        if cursor.rowcount == 0:
            raise ValueError("La cuenta no existe.")


def get_or_create_client(path: str, name: str, phone: str) -> int:
    digits = digits_only(phone)
    if len(digits) < 7:
        raise ValueError("El celular debe tener al menos 7 dígitos.")
    normalized = normalize_phone(phone)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT id, phone FROM clients").fetchall()
        for row in rows:
            stored = digits_only(row["phone"])
            if stored.endswith(digits[-10:]) or digits.endswith(stored[-10:]):
                return int(row["id"])
        cursor = connection.execute(
            "INSERT INTO clients (name, phone, created_at) VALUES (?, ?, ?)",
            (name.strip(), normalized, datetime.now(UTC).isoformat()),
        )
        connection.commit()
        return int(cursor.lastrowid)


def create_client(path: str, name: str, phone: str) -> int:
    with sqlite3.connect(path) as connection:
        cursor = connection.execute(
            "INSERT INTO clients (name, phone, created_at) VALUES (?, ?, ?)",
            (name.strip(), normalize_phone(phone), datetime.now(UTC).isoformat()),
        )
        connection.commit()
        return int(cursor.lastrowid)


def update_client(path: str, client_id: int, name: str, phone: str) -> None:
    with sqlite3.connect(path) as connection:
        cursor = connection.execute(
            "UPDATE clients SET name = ?, phone = ? WHERE id = ?",
            (name.strip(), normalize_phone(phone), client_id),
        )
        connection.commit()
        if cursor.rowcount == 0:
            raise ValueError("El cliente no existe.")


def delete_client(path: str, client_id: int) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM client_accounts WHERE client_id = ?", (client_id,))
        cursor = connection.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        connection.commit()
        if cursor.rowcount == 0:
            raise ValueError("El cliente no existe.")


def unassign_account(path: str, client_id: int, account_id: int) -> None:
    with sqlite3.connect(path) as connection:
        cursor = connection.execute(
            "DELETE FROM client_accounts WHERE client_id = ? AND account_id = ?",
            (client_id, account_id),
        )
        connection.commit()
        if cursor.rowcount == 0:
            raise ValueError("La asociación no existe.")


def assign_account(path: str, client_id: int, account_id: int, assigned_at: str | None = None) -> None:
    assigned = _parse_expires_at(assigned_at) if assigned_at else datetime.now(UTC)
    if assigned is None:
        raise ValueError("La fecha de asociación no es válida.")
    expires = _link_expires_at(assigned)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        account = connection.execute(
            "SELECT platform FROM streaming_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if account is None:
            raise ValueError("La cuenta no existe.")
        duplicate = connection.execute(
            """
            SELECT 1 FROM client_accounts ca
            JOIN streaming_accounts a ON a.id = ca.account_id
            WHERE ca.client_id = ? AND a.platform = ?
            """,
            (client_id, account[0]),
        ).fetchone()
        if duplicate:
            raise ValueError("El cliente ya tiene una cuenta de esta plataforma.")
        connection.execute(
            """
            INSERT INTO client_accounts (client_id, account_id, assigned_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (client_id, account_id, assigned.isoformat(), expires.isoformat()),
        )
        connection.commit()


def find_client_access(path: str, platform: str, identifier: str) -> dict | None:
    """Busca acceso por celular del cliente (no por correo/alias)."""
    digits = digits_only(identifier)
    if len(digits) < 7:
        return None
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT c.id AS client_id, c.name AS client_name, c.phone,
                   a.id AS account_id, a.platform, a.name AS account_name,
                   a.email AS account_email, a.subdomain,
                   a.main_account_id,
                   ca.assigned_at, ca.expires_at,
                   m.email AS main_email, m.password AS main_password,
                   m.imap_host, m.imap_port, m.imap_folder, m.domain AS main_domain
            FROM clients c
            JOIN client_accounts ca ON ca.client_id = c.id
            JOIN streaming_accounts a ON a.id = ca.account_id
            LEFT JOIN main_accounts m ON m.id = a.main_account_id
            WHERE a.platform = ?
            """,
            (platform,),
        ).fetchall()
    for row in rows:
        phone_digits = digits_only(row["phone"])
        phone_match = row["phone"].casefold() == identifier.strip().casefold()
        phone_digits_match = phone_digits.endswith(digits[-10:]) or digits.endswith(phone_digits[-10:])
        if phone_match or phone_digits_match:
            access = dict(row)
            if access.get("main_password"):
                access["main_password"] = _open(access["main_password"])
            # Corte de acceso: 30 días desde la vinculación (ca.expires_at).
            access.update(account_status(access.get("expires_at")))
            return access
    return None
