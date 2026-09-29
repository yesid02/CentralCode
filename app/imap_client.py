import email
import html as html_lib
import imaplib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.header import decode_header
from email.message import Message

from app.config import Settings
from app.platforms import Platform

CODE_PATTERN = re.compile(r"(?<!\d)(\d{4,6})(?!\d)")
OTP_NEAR_MARKER = re.compile(
    r"(?:c[oó]digo|code|otp|pin|inicio de sesi[oó]n|sign[\s-]?in|log[\s-]?in)[^\d]{0,40}(\d{4,6})",
    re.IGNORECASE,
)
HOUSEHOLD_SUBJECT_TERMS = (
    "acceso temporal",
    "temporary access",
    "codigo de acceso temporal",
    "obtener codigo",
    "obtener código",
)
HREF_PATTERN = re.compile(
    r"""href\s*=\s*["'](https?://[^"']+)["']""",
    re.IGNORECASE,
)
CTA_NEAR_HREF = re.compile(
    r"""href\s*=\s*["'](https?://[^"']+)["'][^>]*>[\s\S]{0,200}?obtener\s+c[oó]digo""",
    re.IGNORECASE,
)
NETFLIX_HOST_HINT = re.compile(r"netflix\.com", re.IGNORECASE)


@dataclass(frozen=True)
class MailboxCredentials:
    host: str
    username: str
    password: str
    port: int = 993
    folder: str = "INBOX"


@dataclass
class CodeSearchResult:
    code: str | None = None
    near_miss_recipients: list[str] = field(default_factory=list)


@dataclass
class HouseholdLinkResult:
    link_url: str | None = None
    near_miss_recipients: list[str] = field(default_factory=list)


def _normalize_imap_password(password: str) -> str:
    """Gmail app passwords funcionan mejor sin espacios."""
    return (password or "").replace(" ", "").strip()


def credentials_from_settings(settings: Settings) -> MailboxCredentials:
    return MailboxCredentials(
        host=settings.imap_host,
        username=settings.imap_username,
        password=_normalize_imap_password(settings.imap_password),
        port=settings.imap_port,
        folder=settings.imap_folder,
    )


def credentials_from_main_account(account: dict) -> MailboxCredentials:
    return MailboxCredentials(
        host=account["imap_host"],
        username=account["email"],
        password=_normalize_imap_password(account["password"]),
        port=int(account.get("imap_port") or 993),
        folder=account.get("imap_folder") or "INBOX",
    )


def _imap_ascii(value: str) -> str:
    """IMAP SEARCH solo acepta ASCII; quita tildes (código → codigo)."""
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if ch.isascii()).strip()


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    result: list[str] = []
    for chunk, encoding in decode_header(value):
        if isinstance(chunk, bytes):
            result.append(chunk.decode(encoding or "utf-8", errors="replace"))
        else:
            result.append(chunk)
    return "".join(result)


def _message_text(message: Message) -> str:
    parts: list[str] = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_type() not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    if not parts:
        payload = message.get_payload(decode=True)
        if isinstance(payload, bytes):
            parts.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(parts)


def _subject_matches(subject: str, subjects: tuple[str, ...]) -> bool:
    if not subjects:
        return True
    haystack = subject.casefold()
    haystack_ascii = _imap_ascii(haystack).casefold()
    for term in subjects:
        needle = term.casefold()
        needle_ascii = _imap_ascii(needle).casefold()
        if needle in haystack or (needle_ascii and needle_ascii in haystack_ascii):
            return True
    return False


def extract_otp(text: str) -> str | None:
    """Prioriza el código junto a 'código/code' y luego PINs de 4 dígitos."""
    if not text:
        return None
    near = OTP_NEAR_MARKER.search(text)
    if near:
        return near.group(1)
    found = CODE_PATTERN.findall(text)
    if not found:
        return None
    four = [item for item in found if len(item) == 4]
    if four:
        return four[0]
    return found[0]


def _recipient_blob(message: Message) -> str:
    return "\n".join(
        _decode_header(message.get(header)).casefold()
        for header in ("To", "Delivered-To", "X-Original-To", "Cc", "Envelope-To")
    )


def _identifier_matches(needle: str, recipients: str, body: str) -> bool:
    needle = needle.casefold().strip()
    if not needle:
        return False
    haystack = f"{recipients}\n{body}".casefold()
    if needle in haystack:
        return True
    if "@" in needle:
        local = needle.split("@", 1)[0]
        if local and local in recipients:
            return True
    return False


def _primary_recipient(recipients: str) -> str | None:
    for part in re.split(r"[\s,;<>]+", recipients):
        if "@" in part:
            return part.strip().casefold()
    return None


def find_recent_code(
    settings: Settings,
    platform: Platform,
    identifier: str,
    mailbox: MailboxCredentials | None = None,
) -> CodeSearchResult:
    credentials = mailbox or credentials_from_settings(settings)
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.code_max_age_minutes)
    # IMAP SINCE es por día (y la fecha interna de Gmail puede diferir del Date header).
    # Pedimos desde ayer y filtramos por hora exacta abajo.
    since = (cutoff - timedelta(days=1)).strftime("%d-%b-%Y")
    connection = imaplib.IMAP4_SSL(credentials.host, credentials.port)
    near_miss: list[str] = []
    try:
        connection.login(credentials.username, credentials.password)
        status, _ = connection.select(credentials.folder, readonly=True)
        if status != "OK":
            raise RuntimeError("No se pudo abrir la carpeta configurada del correo.")

        search_parts = [f'SINCE "{since}"']
        ascii_senders = [_imap_ascii(sender) for sender in platform.senders if _imap_ascii(sender)]
        if ascii_senders:
            sender_query = " OR ".join(f'FROM "{sender}"' for sender in ascii_senders)
            search_parts.append(f"({sender_query})")
        else:
            ascii_subjects = [_imap_ascii(subject) for subject in platform.subjects if _imap_ascii(subject)]
            if ascii_subjects:
                subject_query = " OR ".join(f'SUBJECT "{subject}"' for subject in ascii_subjects)
                search_parts.append(f"({subject_query})")

        status, data = connection.search(None, *search_parts)
        if status != "OK":
            raise RuntimeError("No se pudo buscar en el correo.")

        needle = identifier.casefold().strip()
        message_ids = (data[0] or b"").split()
        for message_id in reversed(message_ids[-60:]):
            status, fetched = connection.fetch(message_id, "(RFC822)")
            if status != "OK" or not fetched:
                continue
            raw_message = next((item[1] for item in fetched if isinstance(item, tuple)), None)
            if not isinstance(raw_message, bytes):
                continue
            message = email.message_from_bytes(raw_message)
            try:
                message_date = email.utils.parsedate_to_datetime(message.get("Date", ""))
            except (TypeError, ValueError, IndexError):
                continue
            if message_date is None:
                continue
            if message_date.tzinfo is None:
                message_date = message_date.replace(tzinfo=UTC)
            if message_date < cutoff:
                continue

            sender = _decode_header(message.get("From")).casefold()
            subject = _decode_header(message.get("Subject"))
            if ascii_senders and not any(item.casefold() in sender for item in ascii_senders):
                continue
            if platform.subjects and not _subject_matches(subject, platform.subjects):
                continue

            recipients = _recipient_blob(message)
            body = _message_text(message)
            # Netflix a veces pinta el PIN con espacios: "8 7 6 1"
            normalized_body = re.sub(r"(?<=\d) (?=\d)", "", f"{subject}\n{body}")
            code = extract_otp(normalized_body)
            if not code:
                continue

            if _identifier_matches(needle, recipients, body):
                return CodeSearchResult(code=code)

            recipient = _primary_recipient(recipients)
            if recipient and recipient not in near_miss:
                near_miss.append(recipient)

        return CodeSearchResult(code=None, near_miss_recipients=near_miss[:3])
    finally:
        try:
            connection.logout()
        except imaplib.IMAP4.error:
            pass


def _is_household_subject(subject: str) -> bool:
    haystack = subject.casefold()
    haystack_ascii = _imap_ascii(haystack).casefold()
    if "acceso temporal" in haystack or "acceso temporal" in haystack_ascii:
        return True
    if "temporary access" in haystack or "temporary access" in haystack_ascii:
        return True
    for term in HOUSEHOLD_SUBJECT_TERMS:
        needle = term.casefold()
        needle_ascii = _imap_ascii(needle).casefold()
        if needle in haystack or (needle_ascii and needle_ascii in haystack_ascii):
            return True
    return False


def extract_household_link(html: str) -> str | None:
    """Extrae la URL del CTA 'Obtener código' (o el mejor href de Netflix)."""
    if not html:
        return None

    def _clean(url: str) -> str:
        return html_lib.unescape(url.strip())

    cta = CTA_NEAR_HREF.search(html)
    if cta:
        return _clean(cta.group(1))

    candidates: list[str] = []
    for match in HREF_PATTERN.finditer(html):
        url = _clean(match.group(1))
        if not NETFLIX_HOST_HINT.search(url):
            continue
        lower = url.casefold()
        if any(skip in lower for skip in ("/cdn/", ".png", ".jpg", ".gif", "help.netflix")):
            continue
        candidates.append(url)
    if not candidates:
        return None
    preferred = [
        url
        for url in candidates
        if any(token in url.casefold() for token in ("travel", "code", "account", "verify", "otp", "temp"))
    ]
    return (preferred or candidates)[0]


def find_recent_household_link(
    settings: Settings,
    platform: Platform,
    identifier: str,
    mailbox: MailboxCredentials | None = None,
) -> HouseholdLinkResult:
    credentials = mailbox or credentials_from_settings(settings)
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.code_max_age_minutes)
    since = (cutoff - timedelta(days=1)).strftime("%d-%b-%Y")
    connection = imaplib.IMAP4_SSL(credentials.host, credentials.port)
    near_miss: list[str] = []
    try:
        connection.login(credentials.username, credentials.password)
        status, _ = connection.select(credentials.folder, readonly=True)
        if status != "OK":
            raise RuntimeError("No se pudo abrir la carpeta configurada del correo.")

        search_parts = [f'SINCE "{since}"']
        ascii_senders = [_imap_ascii(sender) for sender in platform.senders if _imap_ascii(sender)]
        if ascii_senders:
            sender_query = " OR ".join(f'FROM "{sender}"' for sender in ascii_senders)
            search_parts.append(f"({sender_query})")

        status, data = connection.search(None, *search_parts)
        if status != "OK":
            raise RuntimeError("No se pudo buscar en el correo.")

        needle = identifier.casefold().strip()
        message_ids = (data[0] or b"").split()
        for message_id in reversed(message_ids[-60:]):
            status, fetched = connection.fetch(message_id, "(RFC822)")
            if status != "OK" or not fetched:
                continue
            raw_message = next((item[1] for item in fetched if isinstance(item, tuple)), None)
            if not isinstance(raw_message, bytes):
                continue
            message = email.message_from_bytes(raw_message)
            try:
                message_date = email.utils.parsedate_to_datetime(message.get("Date", ""))
            except (TypeError, ValueError, IndexError):
                continue
            if message_date is None:
                continue
            if message_date.tzinfo is None:
                message_date = message_date.replace(tzinfo=UTC)
            if message_date < cutoff:
                continue

            sender = _decode_header(message.get("From")).casefold()
            subject = _decode_header(message.get("Subject"))
            if ascii_senders and not any(item.casefold() in sender for item in ascii_senders):
                continue
            if not _is_household_subject(subject):
                continue

            recipients = _recipient_blob(message)
            body = _message_text(message)
            link = extract_household_link(body)
            if not link:
                continue

            if _identifier_matches(needle, recipients, body):
                return HouseholdLinkResult(link_url=link)

            recipient = _primary_recipient(recipients)
            if recipient and recipient not in near_miss:
                near_miss.append(recipient)

        return HouseholdLinkResult(link_url=None, near_miss_recipients=near_miss[:3])
    finally:
        try:
            connection.logout()
        except imaplib.IMAP4.error:
            pass
