from __future__ import annotations

"""Pure engines for Yoru Casino Expansion (v3.23.0).

No Discord/database objects live here. Interactive views own player input while
these helpers own deterministic rules and can be simulation-tested independently.
"""

from dataclasses import dataclass, field
import math
import random
from typing import Iterable


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

HOUSE_EDGE_MINES = 0.04
HOUSE_EDGE_CHICKEN = 0.05
CANDY_PAYOUT_FACTOR = 5.08


def _rng(rng=None):
    return random.SystemRandom() if rng is None else rng


# ---------------------------------------------------------------------------
# Mines — 5x4 board + cashout row in Discord UI
# ---------------------------------------------------------------------------

MINES_ROWS = 4
MINES_COLS = 5
MINES_CELLS = MINES_ROWS * MINES_COLS
MINES_ALLOWED_COUNTS = (3, 5, 7, 9)


def mines_survival_probability(mine_count: int, safe_reveals: int, *, cells: int = MINES_CELLS) -> float:
    mines = int(mine_count)
    reveals = int(safe_reveals)
    if mines <= 0 or mines >= cells:
        raise ValueError("A bombák száma 1 és a mezők száma-1 között legyen.")
    if reveals < 0 or reveals > cells - mines:
        raise ValueError("Hibás felfedésszám.")
    if reveals == 0:
        return 1.0
    return math.comb(cells - mines, reveals) / math.comb(cells, reveals)


def mines_multiplier(mine_count: int, safe_reveals: int, *, cells: int = MINES_CELLS) -> float:
    if int(safe_reveals) <= 0:
        return 1.0
    probability = mines_survival_probability(mine_count, safe_reveals, cells=cells)
    return max(1.0, (1.0 - HOUSE_EDGE_MINES) / probability)


@dataclass(slots=True)
class MinesState:
    mine_count: int
    mines: set[int]
    revealed: set[int] = field(default_factory=set)
    exploded: int | None = None
    finished: bool = False

    @property
    def safe_reveals(self) -> int:
        return len([index for index in self.revealed if index not in self.mines])

    @property
    def multiplier(self) -> float:
        return mines_multiplier(self.mine_count, self.safe_reveals)

    @property
    def remaining_safe(self) -> int:
        return MINES_CELLS - self.mine_count - self.safe_reveals


def new_mines_state(mine_count: int, *, rng=None) -> MinesState:
    mine_count = int(mine_count)
    if mine_count not in MINES_ALLOWED_COUNTS:
        raise ValueError(f"Bombák: {', '.join(map(str, MINES_ALLOWED_COUNTS))}.")
    rnd = _rng(rng)
    return MinesState(mine_count=mine_count, mines=set(rnd.sample(range(MINES_CELLS), mine_count)))


def reveal_mines_cell(state: MinesState, index: int) -> bool:
    if state.finished:
        raise ValueError("Ez a Mines kör már lezárult.")
    index = int(index)
    if not 0 <= index < MINES_CELLS:
        raise ValueError("Hibás mező.")
    if index in state.revealed:
        raise ValueError("Ezt a mezőt már felfedted.")
    state.revealed.add(index)
    if index in state.mines:
        state.exploded = index
        state.finished = True
        return False
    if state.remaining_safe <= 0:
        state.finished = True
    return True


# ---------------------------------------------------------------------------
# Chicken Road — push-your-luck lane crossing
# ---------------------------------------------------------------------------

CHICKEN_STEP_SURVIVAL = (0.90, 0.87, 0.84, 0.81, 0.78, 0.74, 0.70, 0.66)


def chicken_survival_probability(step: int) -> float:
    step = int(step)
    if step < 0 or step > len(CHICKEN_STEP_SURVIVAL):
        raise ValueError("Hibás Chicken Road lépés.")
    probability = 1.0
    for chance in CHICKEN_STEP_SURVIVAL[:step]:
        probability *= chance
    return probability


def chicken_multiplier(step: int) -> float:
    step = int(step)
    if step <= 0:
        return 1.0
    return max(1.0, (1.0 - HOUSE_EDGE_CHICKEN) / chicken_survival_probability(step))


@dataclass(slots=True)
class ChickenRoadState:
    step: int = 0
    alive: bool = True
    finished: bool = False
    last_roll: float | None = None

    @property
    def max_steps(self) -> int:
        return len(CHICKEN_STEP_SURVIVAL)

    @property
    def multiplier(self) -> float:
        return chicken_multiplier(self.step)


def advance_chicken(state: ChickenRoadState, *, rng=None) -> bool:
    if state.finished:
        raise ValueError("Ez a Chicken Road kör már lezárult.")
    if state.step >= state.max_steps:
        state.finished = True
        return True
    rnd = _rng(rng)
    roll = float(rnd.random())
    state.last_roll = roll
    chance = CHICKEN_STEP_SURVIVAL[state.step]
    if roll >= chance:
        state.alive = False
        state.finished = True
        return False
    state.step += 1
    if state.step >= state.max_steps:
        state.finished = True
    return True


# ---------------------------------------------------------------------------
# Plinko — locked v3.25 standard board
# ---------------------------------------------------------------------------

PLINKO_ROWS = 10
# One standard board: the centre is common/low-value, the rare edges are the
# large wins.  With a fair 50/50 left/right peg path the exact code-owned RTP is
# ~95.64%. The rendered board and the paid multiplier must stay identical.
PLINKO_MULTIPLIERS: tuple[float, ...] = (
    50.0, 3.5, 2.2, 1.2, 0.65, 0.20, 0.65, 1.2, 2.2, 3.5, 50.0,
)


@dataclass(frozen=True, slots=True)
class PlinkoResult:
    path: tuple[int, ...]
    slot: int
    multiplier: float


def run_plinko(*, rng=None) -> PlinkoResult:
    rnd = _rng(rng)
    path = tuple(1 if rnd.random() >= 0.5 else 0 for _ in range(PLINKO_ROWS))
    slot = sum(path)
    return PlinkoResult(path=path, slot=slot, multiplier=float(PLINKO_MULTIPLIERS[slot]))


def plinko_exact_rtp() -> float:
    return sum(
        math.comb(PLINKO_ROWS, slot) / (2 ** PLINKO_ROWS) * PLINKO_MULTIPLIERS[slot]
        for slot in range(PLINKO_ROWS + 1)
    )


# ---------------------------------------------------------------------------
# Candy Rush — 6x6 real cascade engine
# ---------------------------------------------------------------------------

CANDY_ROWS = 6
CANDY_COLS = 6
CANDY_SYMBOLS = ("CHERRY", "LEMON", "GRAPE", "BELL", "DIAMOND", "SEVEN")
CANDY_WEIGHTS = (28, 24, 20, 14, 9, 5)
CANDY_VALUES = {
    "CHERRY": 0.45,
    "LEMON": 0.60,
    "GRAPE": 0.80,
    "BELL": 1.10,
    "DIAMOND": 1.60,
    "SEVEN": 2.50,
}
CANDY_MAX_CASCADES = 6


@dataclass(frozen=True, slots=True)
class CandyCascade:
    number: int
    before: tuple[tuple[str, ...], ...]
    matched: frozenset[tuple[int, int]]
    after: tuple[tuple[str, ...], ...]
    multiplier_delta: float


@dataclass(frozen=True, slots=True)
class CandyRushResult:
    initial: tuple[tuple[str, ...], ...]
    cascades: tuple[CandyCascade, ...]
    final: tuple[tuple[str, ...], ...]
    multiplier: float


def _new_candy_grid(rnd) -> list[list[str]]:
    return [rnd.choices(CANDY_SYMBOLS, weights=CANDY_WEIGHTS, k=CANDY_COLS) for _ in range(CANDY_ROWS)]


def candy_matches(grid: list[list[str]] | tuple[tuple[str, ...], ...]) -> set[tuple[int, int]]:
    matches: set[tuple[int, int]] = set()
    for row in range(CANDY_ROWS):
        col = 0
        while col < CANDY_COLS:
            end = col + 1
            while end < CANDY_COLS and grid[row][end] == grid[row][col]:
                end += 1
            if end - col >= 3:
                matches.update((row, c) for c in range(col, end))
            col = end
    for col in range(CANDY_COLS):
        row = 0
        while row < CANDY_ROWS:
            end = row + 1
            while end < CANDY_ROWS and grid[end][col] == grid[row][col]:
                end += 1
            if end - row >= 3:
                matches.update((r, col) for r in range(row, end))
            row = end
    return matches


def _drop_candy(grid: list[list[str]], matched: set[tuple[int, int]], rnd) -> list[list[str]]:
    out = [["" for _ in range(CANDY_COLS)] for _ in range(CANDY_ROWS)]
    for col in range(CANDY_COLS):
        survivors = [grid[row][col] for row in range(CANDY_ROWS) if (row, col) not in matched]
        incoming = rnd.choices(CANDY_SYMBOLS, weights=CANDY_WEIGHTS, k=CANDY_ROWS - len(survivors))
        values = incoming + survivors
        for row, symbol in enumerate(values):
            out[row][col] = symbol
    return out


def run_candy_rush(*, rng=None) -> CandyRushResult:
    rnd = _rng(rng)
    grid = _new_candy_grid(rnd)
    initial = tuple(tuple(row) for row in grid)
    cascades: list[CandyCascade] = []
    total = 0.0
    for number in range(1, CANDY_MAX_CASCADES + 1):
        matched = candy_matches(grid)
        if not matched:
            break
        cascade_boost = 1.0 + (number - 1) * 0.35
        raw = sum(CANDY_VALUES[grid[row][col]] for row, col in matched)
        delta = (raw / float(CANDY_ROWS * CANDY_COLS)) * cascade_boost * CANDY_PAYOUT_FACTOR
        before = tuple(tuple(row) for row in grid)
        grid = _drop_candy(grid, matched, rnd)
        after = tuple(tuple(row) for row in grid)
        cascades.append(CandyCascade(number, before, frozenset(matched), after, delta))
        total += delta
    final = tuple(tuple(row) for row in grid)
    return CandyRushResult(initial=initial, cascades=tuple(cascades), final=final, multiplier=max(0.0, total))


# ---------------------------------------------------------------------------
# Simulation helpers (also useful for release QA)
# ---------------------------------------------------------------------------


def simulate_plinko_rtp(samples: int, *, seed: int = 3230) -> float:
    rnd = random.Random(seed)
    if samples <= 0:
        raise ValueError("samples > 0 szükséges")
    return sum(run_plinko(rng=rnd).multiplier for _ in range(int(samples))) / int(samples)


def simulate_candy_rtp(samples: int, *, seed: int = 3231) -> float:
    """Fast payout-only simulator; skips animation snapshots/dataclass allocation."""
    rnd = random.Random(seed)
    if samples <= 0:
        raise ValueError("samples > 0 szükséges")
    total_all = 0.0
    for _ in range(int(samples)):
        grid = _new_candy_grid(rnd)
        total = 0.0
        for number in range(1, CANDY_MAX_CASCADES + 1):
            matched = candy_matches(grid)
            if not matched:
                break
            cascade_boost = 1.0 + (number - 1) * 0.35
            raw = 0.0
            for row, col in matched:
                raw += CANDY_VALUES[grid[row][col]]
            total += (raw / float(CANDY_ROWS * CANDY_COLS)) * cascade_boost * CANDY_PAYOUT_FACTOR
            grid = _drop_candy(grid, matched, rnd)
        total_all += total
    return total_all / int(samples)
