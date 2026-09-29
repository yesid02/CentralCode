"""Catálogo de venta de cuentas (independiente de la consulta OTP)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShopProduct:
    key: str
    label: str
    price_cop: int
    blurb: str
    category: str


SHOP_CATALOG: tuple[ShopProduct, ...] = (
    ShopProduct("netflix", "Netflix", 25000, "Cuenta compartida / perfil", "Streaming"),
    ShopProduct("disney", "Disney+", 18000, "Incluye Star", "Streaming"),
    ShopProduct("hbo", "Max (HBO)", 20000, "Catálogo completo", "Streaming"),
    ShopProduct("prime", "Prime Video", 15000, "Amazon Prime Video", "Streaming"),
    ShopProduct("paramount", "Paramount+", 14000, "Series y cine", "Streaming"),
    ShopProduct("appletv", "Apple TV+", 16000, "Originales Apple", "Streaming"),
    ShopProduct("starplus", "Star+", 22000, "Deportes y series", "Streaming"),
    ShopProduct("vix", "ViX Premium", 12000, "Contenido en español", "Streaming"),
    ShopProduct("crunchyroll", "Crunchyroll", 17000, "Anime ilimitado", "Streaming"),
    ShopProduct("youtube", "YouTube Premium", 19000, "Sin anuncios + Music", "Streaming"),
    ShopProduct("claro", "Claro Video", 11000, "Pack streaming", "Streaming"),
    ShopProduct("spotify", "Spotify", 15000, "Premium individual", "Música"),
    ShopProduct("applemusic", "Apple Music", 15000, "Catálogo completo", "Música"),
    ShopProduct("deezer", "Deezer", 13000, "HiFi disponible", "Música"),
    ShopProduct("tidal", "Tidal", 18000, "Audio HiFi", "Música"),
    ShopProduct("amazonmusic", "Amazon Music", 14000, "Unlimited", "Música"),
    ShopProduct("canva", "Canva Pro", 22000, "Plantillas y Brand Kit", "Productividad"),
    ShopProduct("notion", "Notion Plus", 20000, "Espacios colaborativos", "Productividad"),
    ShopProduct("office365", "Microsoft 365", 28000, "Office + OneDrive", "Productividad"),
    ShopProduct("adobe", "Adobe Creative Cloud", 45000, "Apps creativas", "Productividad"),
    ShopProduct("chatgpt", "ChatGPT Plus", 35000, "GPT-4o / Plus", "Productividad"),
    ShopProduct("capcut", "CapCut Pro", 16000, "Edición de video", "Productividad"),
    ShopProduct("xbox", "Xbox Game Pass", 30000, "PC o consola", "Gaming"),
    ShopProduct("playstation", "PlayStation Plus", 32000, "Extra / Essential", "Gaming"),
    ShopProduct("ea", "EA Play", 18000, "Catálogo EA", "Gaming"),
    ShopProduct("duolingo", "Duolingo Super", 12000, "Sin vidas limitadas", "Educación"),
    ShopProduct("coursera", "Coursera Plus", 40000, "Cursos ilimitados", "Educación"),
    ShopProduct("nordvpn", "NordVPN", 25000, "VPN premium", "Seguridad"),
    ShopProduct("expressvpn", "ExpressVPN", 28000, "VPN rápida", "Seguridad"),
    ShopProduct("iptv", "IPTV Premium", 20000, "Canales en vivo", "TV"),
)


def list_shop_products() -> list[dict]:
    return [
        {
            "key": product.key,
            "label": product.label,
            "price_cop": product.price_cop,
            "blurb": product.blurb,
            "category": product.category,
        }
        for product in SHOP_CATALOG
    ]


def get_shop_product(key: str) -> ShopProduct | None:
    return next((product for product in SHOP_CATALOG if product.key == key), None)


def format_cop(amount: int) -> str:
    return f"${amount:,}".replace(",", ".")
