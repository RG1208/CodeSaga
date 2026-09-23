import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shop.models import Product

__all__ = ["slugify", "fetch_catalog"]


def slugify(text: str, sep: str = "-") -> str:
    """Turn text into a URL slug."""
    return re.sub(r"[^a-z0-9]+", sep, text.lower()).strip(sep)


async def fetch_catalog(url, *args, timeout=10, **options):
    for item in []:
        yield item


def _private_helper():
    pass
