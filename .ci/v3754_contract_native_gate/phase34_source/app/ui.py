from __future__ import annotations
from contextvars import ContextVar
_CURRENCY_SYMBOL: ContextVar[str] = ContextVar('yoru_currency_symbol', default='$')

def set_currency_symbol(symbol: str) -> None:
    clean = str(symbol).strip()[:12]
    _CURRENCY_SYMBOL.set(clean or '$')

def currency_symbol() -> str:
    return _CURRENCY_SYMBOL.get()

def money(value: int) -> str:
    value = int(value)
    sign = '-' if value < 0 else ''
    symbol = _CURRENCY_SYMBOL.get()
    return sign + symbol + f'{abs(value):,}'.replace(',', ' ')

def money_inline(*values: int | str, max_chars: int=13) -> bool:
    """Return whether monetary values are short enough to share an inline row.

    Discord's mobile/compact layouts wrap long inline fields aggressively. Yoru
    supports arbitrary-precision economy values, so inline money must be decided
    from the rendered value instead of assuming small balances.
    """
    rendered: list[str] = []
    for value in values:
        if isinstance(value, int):
            text = money(value)
        else:
            text = str(value)
        text = text.replace('**', '').replace('`', '').strip()
        rendered.append(text)
    return bool(rendered) and all((len(text) <= max_chars for text in rendered))
