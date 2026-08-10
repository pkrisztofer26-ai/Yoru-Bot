from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN


_SUFFIXES = {
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
    "t": 1_000_000_000_000,
    "q": 1_000_000_000_000_000,
}


def parse_amount(raw: str | int, maximum: int | None = None) -> int:
    """Parse economy amounts consistently across slash and prefix commands.

    Supports plain integers, decimal k/m/b/t/q suffixes and all/max aliases.
    There is no artificial gameplay cap; when ``maximum`` is supplied, the
    user's current wallet/bank balance is the only practical limit.
    """
    value = str(raw).strip().lower().replace(" ", "").replace("_", "")
    if value in {"all", "max", "minden", "osszes", "összes"}:
        if maximum is None or maximum <= 0:
            raise ValueError("Nincs felhasználható összeg.")
        return int(maximum)

    example = "5000, 25k, 2m, 1b, 1.5t, 2q vagy all"
    if not value:
        raise ValueError(f"Az összeg legyen szám, például `{example}`.")

    multiplier = 1
    suffix = value[-1:]
    if suffix in _SUFFIXES:
        multiplier = _SUFFIXES[suffix]
        value = value[:-1]

    try:
        numeric = Decimal(value)
        amount = int((numeric * multiplier).to_integral_value(rounding=ROUND_DOWN))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"Az összeg legyen szám, például `{example}`.") from None

    if amount <= 0:
        raise ValueError("Az összegnek pozitívnak kell lennie.")
    if maximum is not None and amount > maximum:
        raise ValueError("Nincs ennyi felhasználható pénzed.")
    return amount
