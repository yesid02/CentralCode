"""Plataformas de consulta OTP = productos de la tienda."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_SUBJECTS = ("codigo", "code", "verification", "inicio", "login")

# Remitentes por defecto al sembrar productos conocidos (editables después en Tienda).
OTP_SENDER_DEFAULTS: dict[str, tuple[str, ...]] = {
    "netflix": ("netflix.com",),
    "disney": ("disneyplus.com", "disney.com", "starplus.com"),
    "hbo": ("max.com", "hbomax.com", "hbo.com"),
    "prime": ("amazon.com", "primevideo.com"),
    "paramount": ("paramountplus.com", "paramount.com"),
    "appletv": ("apple.com",),
    "starplus": ("starplus.com", "disneyplus.com", "disney.com"),
    "vix": ("vix.com",),
    "crunchyroll": ("crunchyroll.com",),
    "youtube": ("youtube.com", "google.com"),
    "claro": ("clarovideo.com", "claro.com"),
    "spotify": ("spotify.com",),
    "applemusic": ("apple.com",),
    "deezer": ("deezer.com",),
    "tidal": ("tidal.com",),
    "amazonmusic": ("amazon.com",),
    "canva": ("canva.com",),
    "notion": ("notion.so", "makenotion.com"),
    "office365": ("microsoft.com",),
    "adobe": ("adobe.com",),
    "chatgpt": ("openai.com",),
    "capcut": ("capcut.com",),
    "xbox": ("xbox.com", "microsoft.com"),
    "playstation": ("playstation.com", "sony.com"),
    "ea": ("ea.com",),
    "duolingo": ("duolingo.com",),
    "coursera": ("coursera.org",),
    "nordvpn": ("nordvpn.com", "nordaccount.com"),
    "expressvpn": ("expressvpn.com",),
}


@dataclass(frozen=True)
class Platform:
    key: str
    label: str
    senders: tuple[str, ...]
    subjects: tuple[str, ...] = DEFAULT_SUBJECTS


def _parse_csv(value: str | None, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not value or not str(value).strip():
        return fallback
    parts = tuple(part.strip() for part in str(value).split(",") if part.strip())
    return parts or fallback


def platform_from_product(product: dict) -> Platform:
    key = product["key"]
    senders_fallback = OTP_SENDER_DEFAULTS.get(key, ())
    subjects_fallback = DEFAULT_SUBJECTS
    return Platform(
        key=key,
        label=product["label"],
        senders=_parse_csv(product.get("otp_senders"), senders_fallback),
        subjects=_parse_csv(product.get("otp_subjects"), subjects_fallback),
    )


def list_platforms(path: str, *, active_only: bool = True) -> list[dict[str, str]]:
    from app.shop_store import list_shop_products_admin

    products = list_shop_products_admin(path)
    result = []
    for product in products:
        if active_only and not product.get("active"):
            continue
        result.append({"key": product["key"], "label": product["label"]})
    return result


def get_platform(path: str, key: str) -> Platform | None:
    from app.shop_store import get_shop_product_by_key

    product = get_shop_product_by_key(path, key)
    if product is None:
        return None
    return platform_from_product(product)
