from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque


@dataclass(frozen=True, slots=True)
class LatencySnapshot:
    count: int
    avg_ms: float
    max_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float


class RollingLatency:
    """Bounded in-process latency reservoir with cheap percentile snapshots.

    Yoru needs live p50/p95/p99 visibility without an unbounded metrics list.
    Only the most recent ``max_samples`` observations are retained. Recording is
    O(1); percentile sorting happens only when a diagnostic snapshot is read.
    """

    def __init__(self, *, max_samples: int = 2048) -> None:
        self._samples: Deque[float] = deque(maxlen=max(32, int(max_samples)))
        self._total_count = 0
        self._total_ms = 0.0
        self._max_ms = 0.0

    @property
    def retained_count(self) -> int:
        return len(self._samples)

    @property
    def total_count(self) -> int:
        return self._total_count

    def observe(self, value_ms: float) -> None:
        value = max(0.0, float(value_ms))
        self._samples.append(value)
        self._total_count += 1
        self._total_ms += value
        self._max_ms = max(self._max_ms, value)

    def reset(self) -> None:
        self._samples.clear()
        self._total_count = 0
        self._total_ms = 0.0
        self._max_ms = 0.0

    @staticmethod
    def _percentile(sorted_values: list[float], percentile: float) -> float:
        if not sorted_values:
            return 0.0
        if len(sorted_values) == 1:
            return sorted_values[0]
        p = max(0.0, min(1.0, float(percentile)))
        index = p * (len(sorted_values) - 1)
        lower = int(index)
        upper = min(len(sorted_values) - 1, lower + 1)
        if lower == upper:
            return sorted_values[lower]
        fraction = index - lower
        return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction

    def snapshot(self) -> LatencySnapshot:
        values = sorted(self._samples)
        return LatencySnapshot(
            count=self._total_count,
            avg_ms=(self._total_ms / self._total_count) if self._total_count else 0.0,
            max_ms=self._max_ms,
            p50_ms=self._percentile(values, 0.50),
            p95_ms=self._percentile(values, 0.95),
            p99_ms=self._percentile(values, 0.99),
        )
