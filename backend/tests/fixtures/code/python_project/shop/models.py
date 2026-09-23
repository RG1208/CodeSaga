"""Domain models."""

from dataclasses import dataclass, field


class BaseModel:
    """Base class for all models."""

    def validate(self) -> bool:
        return True


@dataclass(frozen=True)
class Product(BaseModel):
    """A product for sale."""

    name: str
    price: float = 0.0
    tags: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.price})"

    @classmethod
    def free(cls, name: str) -> "Product":
        return cls(name=name)

    # Apply a percentage discount.
    def discounted(self, percent: float, *, round_to: int = 2) -> float:
        self.validate()
        return round(self.price * (1 - percent / 100), round_to)
