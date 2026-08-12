from __future__ import annotations

"""Reusable primitives for Yoru Interactive Jobs / Activities.

The framework deliberately contains no Discord objects and no database access.  A
job service owns persistence while these helpers own deterministic game rules, so
future activities (Heist Lite, new jobs, grid/pattern games) can reuse the same
logic and be unit-tested without a Discord client.
"""

from dataclasses import dataclass
import random
from typing import Sequence, TypeVar

T = TypeVar("T")


def clamp_score(value: int) -> int:
    return max(0, min(100, int(value)))


@dataclass(frozen=True, slots=True)
class SkillCheckResult:
    success: bool
    score_delta: int = 0
    reward_delta: int = 0
    label: str = ""


@dataclass(frozen=True, slots=True)
class PerformanceRating:
    grade: str
    score: int

    @classmethod
    def from_score(cls, score: int) -> "PerformanceRating":
        score = clamp_score(score)
        if score >= 92:
            grade = "S"
        elif score >= 78:
            grade = "A"
        elif score >= 62:
            grade = "B"
        elif score >= 45:
            grade = "C"
        else:
            grade = "D"
        return cls(grade=grade, score=score)


@dataclass(slots=True)
class PerformanceTracker:
    score: int = 50
    combo: int = 0
    best_combo: int = 0

    def apply(self, result: SkillCheckResult) -> int:
        self.score = clamp_score(self.score + int(result.score_delta))
        if result.success:
            self.combo += 1
            self.best_combo = max(self.best_combo, self.combo)
        else:
            self.combo = 0
        return self.score


@dataclass(frozen=True, slots=True)
class SequenceRound:
    sequence: tuple[str, ...]
    candidates: tuple[tuple[str, ...], ...]
    answer_index: int


class SequenceGame:
    """Builds a memory/sequence round with one correct and unique decoys."""

    @staticmethod
    def build_round(
        tokens: Sequence[str],
        *,
        length: int = 4,
        candidate_count: int = 4,
        rng: random.Random | random.SystemRandom | None = None,
    ) -> SequenceRound:
        if length < 2:
            raise ValueError("A sequence legalább 2 elemű legyen.")
        if len(tokens) < length:
            raise ValueError("Nincs elég egyedi token a sequence-hez.")
        if candidate_count < 2:
            raise ValueError("Legalább 2 válaszlehetőség szükséges.")
        rnd = rng or random.SystemRandom()
        sequence = tuple(rnd.sample(list(tokens), length))
        candidates: list[tuple[str, ...]] = [sequence]

        # For a 4-token round there are plenty of permutations.  The attempt
        # cap prevents a pathological custom RNG from looping forever.
        attempts = 0
        while len(candidates) < candidate_count and attempts < 250:
            attempts += 1
            wrong = list(sequence)
            rnd.shuffle(wrong)
            candidate = tuple(wrong)
            if candidate not in candidates:
                candidates.append(candidate)
        if len(candidates) != candidate_count:
            raise RuntimeError("Nem sikerült elég egyedi sequence opciót generálni.")

        rnd.shuffle(candidates)
        return SequenceRound(sequence, tuple(candidates), candidates.index(sequence))


class MemoryGame(SequenceGame):
    """Semantic alias for activities that briefly reveal then hide a pattern."""


class GridGame:
    @staticmethod
    def validate_pick(index: int, *, cell_count: int, revealed: Sequence[int]) -> int:
        idx = int(index)
        if not 0 <= idx < int(cell_count):
            raise ValueError("Hibás mező.")
        if idx in {int(item) for item in revealed}:
            raise ValueError("Ezt a mezőt már átnézted.")
        return idx


@dataclass(frozen=True, slots=True)
class RiskCashout:
    """Shared push-your-luck state for future Jobs/Heist activities."""

    banked: int = 0
    at_risk: int = 0

    def add(self, amount: int) -> "RiskCashout":
        return RiskCashout(self.banked, max(0, self.at_risk + int(amount)))

    def cashout(self) -> "RiskCashout":
        return RiskCashout(self.banked + self.at_risk, 0)

    def fail(self, *, keep_fraction: float = 0.0) -> "RiskCashout":
        keep = round(self.at_risk * max(0.0, min(1.0, float(keep_fraction))))
        return RiskCashout(self.banked + keep, 0)
