"""Stock bookkeeping."""


def restock(stock: dict[str, int], item: str, qty: int) -> dict[str, int]:
    """Add qty units of item to stock."""
    if qty <= 0:
        raise ValueError("qty must be positive")
    stock[item] = stock.get(item, 0) + qty
    return stock


def reserve(stock: dict[str, int], item: str, qty: int) -> dict[str, int]:
    """Remove qty units of item from stock for an order."""
    available = stock.get(item, 0)
    if qty > available:
        raise ValueError(f"only {available} {item} left")
    stock[item] = available - qty
    return stock
