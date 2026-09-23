from ..services import ProductService, create_product
from ..missing_module import nothing
import requests


def route(path):
    def decorator(function):
        return function

    return decorator


@route("/products")
def list_products(service: ProductService):
    product = create_product("Tea", 3.5)
    return service.save(product)
