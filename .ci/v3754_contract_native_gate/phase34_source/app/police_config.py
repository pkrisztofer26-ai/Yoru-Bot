from __future__ import annotations

from dataclasses import dataclass


# Exact points are internal only. Player-facing UI receives qualitative status.
DECAY_POINTS_PER_HOUR = 2
MAX_ATTENTION = 100


@dataclass(frozen=True, slots=True)
class PoliceStatus:
    key: str
    name: str
    emoji: str
    description: str


STATUSES: tuple[tuple[int, PoliceStatus], ...] = (
    (85, PoliceStatus("wanted", "Körözés alatt", "🚨", "A rendőrség aktívan keres. A komolyabb illegális ügyek most különösen veszélyesek.")),
    (60, PoliceStatus("high", "Fokozott figyelem alatt", "🚔", "A rendőrség már komolyabban foglalkozik veled.")),
    (35, PoliceStatus("watched", "Szemmel tartanak", "👁️", "Több nyom és feltűnő ügy kapcsolódik hozzád.")),
    (15, PoliceStatus("noticed", "Felfigyeltek rád", "👮", "Már nem vagy teljesen ismeretlen a rendőrség számára.")),
    (0, PoliceStatus("quiet", "Nem foglalkoznak veled", "🟢", "Jelenleg nincs rajtad számottevő rendőrségi figyelem.")),
)


def status_for(points: int) -> PoliceStatus:
    value = max(0, min(MAX_ATTENTION, int(points)))
    for threshold, status in STATUSES:
        if value >= threshold:
            return status
    return STATUSES[-1][1]
