"""Price calculations."""


def calc_price(base: float, qty: int) -> float:
    """Total price for qty units at the given base price."""
    if qty < 0:
        raise ValueError("qty must be non-negative")
    return round(base * qty, 2)


def apply_discount(price: float, pct: float) -> float:
    """Apply a percentage discount (0-100)."""
    if not 0 <= pct <= 100:
        raise ValueError("pct must be between 0 and 100")
    return round(price * (1 - pct / 100), 2)
