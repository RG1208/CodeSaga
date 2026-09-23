import json

from . import utils
from .models import Product
from shop.utils import slugify as make_slug


def create_product(name: str, price: float) -> Product:
    """Create a product with a slug tag."""
    product = Product(name=name, price=price, tags=[make_slug(name)])
    product.validate()
    return product


class ProductService:
    def __init__(self, store):
        self.store = store

    def save(self, product: Product) -> str:
        self.check(product)
        payload = json.dumps({"name": product.name, "slug": utils.slugify(product.name)})
        return payload

    def check(self, product):
        if not product.validate():
            raise ValueError("invalid")
