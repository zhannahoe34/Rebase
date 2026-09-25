"""Shipping costs."""


def shipping_cost(weight_kg: float) -> float:
    """Flat fee plus a per-kilo rate."""
    return round(5.0 + 1.5 * weight_kg, 2)
