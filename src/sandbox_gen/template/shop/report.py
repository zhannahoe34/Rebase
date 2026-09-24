"""Human-readable reports."""


def stock_report(stock: dict[str, int]) -> str:
    """One line per item, sorted by name."""
    return "\n".join(f"{item}: {qty}" for item, qty in sorted(stock.items()))
