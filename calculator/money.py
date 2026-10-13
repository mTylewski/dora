"""Money helpers. Amounts are integers in grosze; intermediate math uses Decimal."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

GROSZE_PER_PLN = 100


def pln_to_grosze(amount: Decimal | int | str) -> int:
    """Convert a PLN amount to grosze. Rejects floats and sub-grosz precision."""
    if isinstance(amount, float):
        raise TypeError("float is not allowed for money; use Decimal or str")
    value = Decimal(amount) * GROSZE_PER_PLN
    if value != value.to_integral_value():
        raise ValueError(f"amount has more than 2 decimal places: {amount}")
    return int(value)


def round_grosze(value: Decimal, rounding: str = ROUND_HALF_UP) -> int:
    """Round an exact Decimal amount in grosze to a whole grosz."""
    return int(value.quantize(Decimal(1), rounding=rounding))


def format_pln(grosze: int) -> str:
    """Polish format: 12 345,67 zł (non-breaking spaces as thousands separator)."""
    sign = "-" if grosze < 0 else ""
    zl, gr = divmod(abs(grosze), GROSZE_PER_PLN)
    zl_str = f"{zl:,}".replace(",", " ")
    return f"{sign}{zl_str},{gr:02d} zł"
