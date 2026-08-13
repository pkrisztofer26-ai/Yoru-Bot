from __future__ import annotations

"""Shared presentation / interaction primitives for Yoru Casino.

v3.25 starts the visual-framework migration with Plinko.  This module contains
only reusable, game-agnostic helpers; game engines still own RNG and the casino
service/database still own money settlement.
"""

from dataclasses import dataclass
import math

# Locked generic Casino visual language.  Discord components themselves keep
# native Discord colors; these RGB values are for rendered images/GIFs.
CASINO_BG = (18, 19, 25)
CASINO_PANEL = (25, 26, 34)
CASINO_PANEL_SOFT = (31, 32, 42)
CASINO_BORDER = (57, 59, 72)
CASINO_TEXT = (245, 246, 250)
CASINO_MUTED = (157, 160, 173)
CASINO_ACCENT = (137, 78, 224)
CASINO_ACCENT_SOFT = (91, 50, 145)
CASINO_MAGENTA = (222, 64, 155)
CASINO_GREEN = (81, 203, 126)
CASINO_RED = (235, 78, 88)
CASINO_GOLD = (235, 183, 69)


@dataclass(frozen=True, slots=True)
class CasinoVisualStats:
    bet: int
    active: int = 0
    active_limit: int = 10
    total_bet: int = 0
    profit: int = 0


def compact_amount(value: int) -> str:
    """Compact integer money for rendered HUD labels (10.00B, 650.00M...)."""
    n = int(value)
    sign = "-" if n < 0 else ""
    x = abs(n)
    units = ((10**12, "T"), (10**9, "B"), (10**6, "M"), (10**3, "K"))
    for base, suffix in units:
        if x >= base:
            shown = x / base
            precision = 2 if shown < 100 else (1 if shown < 1000 else 0)
            return f"{sign}{shown:.{precision}f}{suffix}"
    return f"{sign}{x}"


def _nice_bet_ladder_neighbour(value: int, direction: int, minimum: int) -> int:
    """Move through a 1/2/5 × 10^n casino-style bet ladder."""
    value = max(int(minimum), int(value))
    minimum = max(1, int(minimum))
    if value <= 0:
        return minimum

    exponent = int(math.floor(math.log10(value)))
    candidates: set[int] = {minimum}
    for exp in range(max(-1, exponent - 2), exponent + 3):
        scale = 10 ** exp
        for lead in (1, 2, 5):
            candidate = int(lead * scale)
            if candidate >= minimum:
                candidates.add(candidate)
    ordered = sorted(candidates)

    if direction > 0:
        for candidate in ordered:
            if candidate > value:
                return candidate
        return max(value + minimum, value * 2)
    for candidate in reversed(ordered):
        if candidate < value:
            return candidate
    return minimum


def adjust_bet(current: int, wallet: int, action: str, *, minimum: int = 1) -> int:
    """Pure bet-control helper.  `all` is intentionally wallet-only.

    No money moves here; the actual Drop/Spin validates and atomically reserves
    the chosen stake at execution time.
    """
    wallet = max(0, int(wallet))
    minimum = max(1, int(minimum))
    current = max(minimum, int(current))
    action = str(action).strip().lower()

    if action == "all":
        if wallet < minimum:
            raise ValueError("Nincs elég pénz a tárcádban a minimum téthez.")
        return wallet
    if action in {"half", "1/2", "½"}:
        value = max(minimum, current // 2)
    elif action in {"double", "x2", "2x"}:
        value = current * 2
    elif action in {"minus", "-"}:
        value = _nice_bet_ladder_neighbour(current, -1, minimum)
    elif action in {"plus", "+"}:
        value = _nice_bet_ladder_neighbour(current, 1, minimum)
    else:
        raise ValueError("Ismeretlen tétmódosítás.")

    # Controls must never silently pull from bank.  Capping to current wallet
    # makes the selected value immediately usable while the Drop still performs
    # the authoritative DB-side balance check.
    if wallet >= minimum:
        value = min(value, wallet)
    return max(minimum, value)
