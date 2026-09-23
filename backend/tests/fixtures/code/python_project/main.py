import shop.services
from shop import utils


def main():
    shop.services.create_product("Coffee", 4.0)
    print(utils.slugify("Hello World"))


if __name__ == "__main__":
    main()
