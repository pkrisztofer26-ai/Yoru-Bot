from __future__ import annotations

"""Domain-owned NPC favor effect contracts.

This module only describes *what* an already-redeemed favor may mean for a
specific owning domain. It never charges money, grants items, mutates XP or
settles gameplay by itself.

A favor is first redeemed by the relationship layer into an active semantic
voucher. The owning domain may later consume that voucher in the same DB
transaction as its authoritative settlement.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FavorEffectDefinition:
    key: str
    npc_key: str
    domain: str
    label: str
    player_description: str
    discount_bp: int = 0
    max_savings: int = 0

    def savings(self, base_price: int) -> int:
        base = max(0, int(base_price))
        if base <= 0 or self.discount_bp <= 0:
            return 0
        raw = base * int(self.discount_bp) // 10_000
        if self.max_savings > 0:
            raw = min(raw, int(self.max_savings))
        return max(0, min(base, raw))


FAVOR_EFFECTS: tuple[FavorEffectDefinition, ...] = (
    FavorEffectDefinition(
        "jani_repair_discount",
        "jani_mechanic",
        "vehicle",
        "Kedvezmény a következő szervizre",
        "Jani a következő fizetős szervized munkadíjából enged. A kedvezményt a Jármű rendszer automatikusan számolja el.",
        discount_bp=2500,
        max_savings=300_000,
    ),
    FavorEffectDefinition(
        "misi_dealership_discount",
        "misi_car_dealer",
        "vehicle",
        "Kedvezmény a következő kereskedéses autóra",
        "Misi a következő, kereskedésből vett autód árán tud javítani. A kedvezményt a Jármű rendszer automatikusan számolja el.",
        discount_bp=500,
        max_savings=500_000,
    ),
    FavorEffectDefinition(
        "bence_business_license_discount",
        "bence_business_contact",
        "business",
        "Kedvezmény a vállalkozói engedélyre",
        "Bence a következő vállalkozói engedélyed ügyintézési költségéből tud lefaragni. A kedvezményt a Vállalkozás rendszer számolja el.",
        discount_bp=1000,
        max_savings=500_000,
    ),
)

FAVOR_EFFECT_BY_KEY = {item.key: item for item in FAVOR_EFFECTS}
FAVOR_EFFECT_BY_NPC = {item.npc_key: item for item in FAVOR_EFFECTS}


def effect(key: str) -> FavorEffectDefinition:
    value = FAVOR_EFFECT_BY_KEY.get(str(key).strip().lower())
    if value is None:
        raise KeyError(f"Ismeretlen favor effect: {key}")
    return value


def effect_for_npc(npc_key: str) -> FavorEffectDefinition | None:
    return FAVOR_EFFECT_BY_NPC.get(str(npc_key).strip().lower())
